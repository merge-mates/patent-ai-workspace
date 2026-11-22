"""묶음 하나의 모델 호출 실패는 그 묶음만 보류한다 (이슈 #211, #166 (가)).

방향·의견서·보정 단계마다: 판단 단위 둘 중 하나의 호출이 실패하면 나머지 결과는 남고,
실패한 묶음은 보류 + 확인되지 않음 + 이유("직접 판단 필요")로 남는다.
한 단계의 모든 묶음이 실패하면 그 단계가 못 돈 것이라 예외로 올린다.
호출 상한에 닿으면 실패가 아니라 limit_reached로 보류하고 끝낸다 (ADR 0003).
"""

import json
from pathlib import Path

import pytest

from patent_ai.core.f4_response_draft.config import F4Options
from patent_ai.core.f4_response_draft.directions import build_directions
from patent_ai.core.f4_response_draft.inputs import F4Input
from patent_ai.core.f4_response_draft.run import run_f4
from patent_ai.core.llm.config import load_step_config
from patent_ai.core.llm.errors import ModelOutputInvalid
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.common import Flag, StatusValue, UnverifiedReason

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "f4"
UNIT_INVENTIVE = "oa_1:29-2:c1"
UNIT_CLARITY = "oa_1:42-4-2:c2"
BAD = TransportResponse("답변입니다", 100, 50)  # JSON이 아님 -> 출력 검사 실패
ONE, TWO = "direction_inventive", "direction_clarity"


def _answer(name: str) -> TransportResponse:
    text = (FIXTURES / "llm" / f"{name}.json").read_text("utf-8")
    return TransportResponse(text, 100, 50)


def _case() -> F4Input:
    data = json.loads((FIXTURES / "case_basic.json").read_text("utf-8"))
    data["spec"] = json.loads((FIXTURES / "spec_basic.pages.json").read_text("utf-8"))
    return F4Input.model_validate(data)


def _ctx(directions=(), opinions=(), amendments=(), used=None):
    def items(xs):
        return [_answer(x) if isinstance(x, str) else x for x in xs]

    transport = FakeTransport(
        {
            "f4.direction": items(directions),
            "f4.opinion": items(opinions),
            "f4.amendment": items(amendments),
        }
    )
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    for step in used or ():  # 이 단계 호출을 상한만큼 이미 쓴 것으로 센다
        for _ in range(load_step_config(step).max_model_calls):
            ctx.budget.add(ctx.run_id, step, 0)
    return ctx, transport


# ---- 방향 후보 ----
def test_방향_후보_묶음_하나가_실패해도_나머지는_남고_그_묶음은_직접_판단_필요():
    ctx, _ = _ctx(directions=[BAD, BAD, TWO])
    first, second = build_directions(_case(), ctx)
    assert first.unit_id == UNIT_INVENTIVE and first.candidates == []
    assert first.status.value == StatusValue.UNVERIFIED
    assert first.status.reason == UnverifiedReason.NOT_EXTRACTED
    assert Flag.NEEDS_HUMAN_JUDGMENT in first.flags  # 보류 글자 (F4): 직접 판단 필요
    assert first.selection is None
    assert "ModelOutputInvalid" in (first.recheck_reason or "")  # 이유가 남는다
    assert second.unit_id == UNIT_CLARITY and len(second.candidates) == 1


def test_방향_후보_모든_묶음이_실패하면_예외로_올린다():
    ctx, _ = _ctx(directions=[BAD] * 4)
    with pytest.raises(ModelOutputInvalid):
        build_directions(_case(), ctx)


def test_방향_후보에서_프로그래밍_오류는_잡지_않는다(monkeypatch):
    def broken(*args, **kwargs):
        raise TypeError("버그")

    monkeypatch.setattr("patent_ai.core.f4_response_draft.directions.call_with_one_retry", broken)
    ctx, _ = _ctx()
    with pytest.raises(TypeError):
        build_directions(_case(), ctx)


def test_방향_후보가_상한에_닿으면_limit_reached로_보류하고_끝낸다():
    ctx, transport = _ctx(used=["f4.direction"])
    results = build_directions(_case(), ctx)  # 실패가 아니라 예외 없이 끝남
    assert [r.unit_id for r in results] == [UNIT_INVENTIVE, UNIT_CLARITY]
    for r in results:
        assert r.candidates == [] and Flag.NEEDS_HUMAN_JUDGMENT in r.flags
        assert r.status.reason == UnverifiedReason.LIMIT_REACHED
        assert "max_model_calls" in (r.recheck_reason or "")
    assert transport.calls == []


# ---- 의견서 ----
def test_의견서_묶음_하나가_실패해도_나머지_의견서는_남고_그_묶음은_보류():
    ctx, _ = _ctx(
        directions=[ONE, TWO],
        opinions=[BAD, BAD, "opinion_clarity"],
        amendments=["amendment_clarity"],
    )
    out = run_f4(_case(), ctx=ctx)
    assert [b.unit_id for b in out.drafts.based_on] == [UNIT_CLARITY]
    assert UNIT_INVENTIVE in out.held_units
    assert Flag.NEEDS_HUMAN_JUDGMENT in out.drafts.flags
    # 보정 단계는 실패한 묶음을 모델 없이 보류하고 청구항 자리에 이유를 남긴다
    held = next(c for c in out.drafts.claims if c.unit_id == UNIT_INVENTIVE)
    # 이유 글에 어느 단계에서 왜(예외 종류)인지 남는다
    assert held.ai_text is None and "직접 판단" in held.held_reason
    assert "의견서 단계" in held.held_reason and "ModelOutputInvalid" in held.held_reason
    assert out.status.value == StatusValue.UNVERIFIED
    assert out.status.reason == UnverifiedReason.NOT_EXTRACTED


def test_의견서_모든_묶음이_실패해도_예외가_아니라_모두_보류이고_이유가_남는다():
    ctx, _ = _ctx(directions=[ONE, TWO], opinions=[BAD] * 4)
    out = run_f4(_case(), ctx=ctx)  # 방향 후보는 만들었으므로 실행은 이어진다
    assert out.drafts is None and len(out.directions) == 2
    assert out.held_units == [UNIT_INVENTIVE, UNIT_CLARITY]
    assert out.status.value == StatusValue.UNVERIFIED
    assert out.status.reason == UnverifiedReason.NOT_EXTRACTED


def test_의견서가_상한에_닿으면_실패가_아니라_limit_reached로_보류하고_끝낸다():
    ctx, _ = _ctx(directions=[ONE, TWO], used=["f4.opinion"])
    out = run_f4(_case(), ctx=ctx)
    assert out.drafts is None and out.held_units == [UNIT_INVENTIVE, UNIT_CLARITY]
    assert Flag.NEEDS_HUMAN_JUDGMENT in out.flags
    assert out.status.value == StatusValue.UNVERIFIED
    assert out.status.reason == UnverifiedReason.LIMIT_REACHED  # 초안이 없어도 이유가 남는다


# ---- 보정 청구항 ----
def test_보정_묶음_하나가_실패해도_나머지_초안은_남고_그_묶음은_보류():
    ctx, _ = _ctx(
        directions=[ONE, TWO],
        opinions=["opinion_inventive", "opinion_clarity"],
        amendments=[BAD, BAD, "amendment_clarity"],
    )
    out = run_f4(_case(), ctx=ctx)
    assert out.held_units == [UNIT_INVENTIVE]
    by_claim = {c.claim: c for c in out.drafts.claims}
    assert by_claim[2].ai_text is not None  # 명확성 묶음 초안은 남는다
    assert by_claim[1].ai_text is None and by_claim[1].held_reason
    assert Flag.NEEDS_HUMAN_JUDGMENT in out.drafts.flags


def test_보정_모든_묶음이_실패해도_예외가_아니라_모두_보류이고_이유가_청구항에_남는다():
    ctx, _ = _ctx(
        directions=[ONE, TWO],
        opinions=["opinion_inventive", "opinion_clarity"],
        amendments=[BAD] * 4,
    )
    out = run_f4(_case(), ctx=ctx)
    assert out.held_units == [UNIT_INVENTIVE, UNIT_CLARITY]
    assert all("보정 단계" in c.held_reason for c in out.drafts.claims)
    assert out.drafts.status.reason == UnverifiedReason.NOT_EXTRACTED


def test_보정이_상한에_닿으면_limit_reached가_초안_status에_남는다():
    ctx, _ = _ctx(
        directions=[ONE, TWO],
        opinions=["opinion_inventive", "opinion_clarity"],
        used=["f4.amendment"],
    )
    out = run_f4(_case(), ctx=ctx)
    assert out.held_units == [UNIT_INVENTIVE, UNIT_CLARITY]
    assert all(c.ai_text is None and c.held_reason for c in out.drafts.claims)
    assert all("max_model_calls" in c.held_reason for c in out.drafts.claims)
    assert out.drafts.status.reason == UnverifiedReason.LIMIT_REACHED


# ---- 단계 전체가 못 돎 = 방향 후보 호출이 모델을 부른 모든 묶음에서 실패했을 때만 ----
def _argue_only() -> TransportResponse:
    """진보성 묶음에서 보정 없이 반박하는 후보 하나만 1등인 답 (보정 단계가 부르지 않는 묶음)."""
    import copy

    only = copy.deepcopy(
        json.loads((FIXTURES / "llm" / "direction_inventive.json").read_text("utf-8"))
    )
    only["candidates"] = only["candidates"][1:]
    only["candidates"][0]["rank"] = 1
    return TransportResponse(json.dumps(only, ensure_ascii=False), 100, 50)


def test_확신_낮은_묶음이_있어도_의견서_실패는_그_묶음_보류일_뿐_실행을_못_돌게_하지_않는다():
    ctx, _ = _ctx(directions=[ONE, "direction_low"], opinions=[BAD, BAD])
    out = run_f4(_case(), ctx=ctx)  # 예외 없이 끝난다
    assert out.drafts is None and out.held_units == [UNIT_INVENTIVE, UNIT_CLARITY]
    assert Flag.NEEDS_HUMAN_JUDGMENT in out.flags


def test_반박만_하는_묶음이_있어도_보정_실패는_그_묶음_보류일_뿐_실행을_못_돌게_하지_않는다():
    no_amendment = json.loads((FIXTURES / "llm" / "opinion_inventive.json").read_text("utf-8"))
    no_amendment["amendment"] = None  # 보정 없이 반박하는 방향의 의견서에는 보정 설명이 없다
    ctx, _ = _ctx(
        directions=[_argue_only(), TWO],
        opinions=[TransportResponse(json.dumps(no_amendment), 100, 50), "opinion_clarity"],
        amendments=[BAD, BAD],
    )
    out = run_f4(_case(), ctx=ctx)
    assert out.held_units == [UNIT_CLARITY]
    assert [b.unit_id for b in out.drafts.based_on] == [UNIT_INVENTIVE, UNIT_CLARITY]


def test_F3가_상한으로_보류한_것은_F4_후보에서도_limit_reached로_남는다():
    data = json.loads((FIXTURES / "case_basic.json").read_text("utf-8"))
    # 실제로 F3는 상한에 닿은 대비 묶음의 대비표를 남기지 않는다 (보류만 남김)
    data["tables"] = [t for t in data["tables"] if t["unit_id"] != UNIT_INVENTIVE]
    data["held_tasks"] = [
        {"task": f"f3_compare:{UNIT_INVENTIVE}:limit_reached", "waiting_for": "원문 확인 필요"}
    ]
    ctx, _ = _ctx(directions=[ONE, TWO])
    first, second = build_directions(F4Input.model_validate(data), ctx)
    assert first.status.reason == UnverifiedReason.LIMIT_REACHED
    assert all(c.status.reason == UnverifiedReason.LIMIT_REACHED for c in first.candidates)
    assert second.status.reason != UnverifiedReason.LIMIT_REACHED


# ---- 묶음 수 상한 max_units: 넘는 묶음은 호출 없이 limit_reached 보류, 실행은 failed가 아님 ----
def test_묶음_수가_max_units를_넘으면_앞_묶음만_처리하고_나머지는_세_단계_모두_보류():
    options = F4Options(final_rejection_limit=False, max_units=1, max_candidates=3)
    ctx, transport = _ctx(
        directions=[ONE], opinions=["opinion_inventive"], amendments=["amendment_inventive"]
    )
    out = run_f4(_case(), ctx=ctx, options=options)  # 예외 없음
    # 호출은 앞 묶음 하나분만: 방향 1 + 의견서 1 + 보정 1
    assert [c["step"] for c in transport.calls] == ["f4.direction", "f4.opinion", "f4.amendment"]
    assert [b.unit_id for b in out.drafts.based_on] == [UNIT_INVENTIVE]
    assert out.held_units == [UNIT_CLARITY]
    rest = next(d for d in out.directions if d.unit_id == UNIT_CLARITY)
    assert rest.status.reason == UnverifiedReason.LIMIT_REACHED
    assert Flag.NEEDS_HUMAN_JUDGMENT in out.flags
    held = next(c for c in out.drafts.claims if c.unit_id == UNIT_CLARITY)
    assert held.ai_text is None and "max_units" in held.held_reason
    assert out.status.value == StatusValue.UNVERIFIED
    assert (
        out.status.reason == UnverifiedReason.LIMIT_REACHED
    )  # 이유가 다른 status에 가려지지 않는다
    assert out.uncovered == []
    assert "직접 판단" in held.held_reason


def test_상한으로_자르기는_목록_순서가_아니라_order_순이다():
    data = json.loads((FIXTURES / "case_basic.json").read_text("utf-8"))
    data["spec"] = json.loads((FIXTURES / "spec_basic.pages.json").read_text("utf-8"))
    data["units"].reverse()  # 목록은 명확성 묶음이 앞, order는 진보성 묶음이 앞
    options = F4Options(final_rejection_limit=False, max_units=1, max_candidates=3)
    ctx, _ = _ctx(directions=[ONE])
    results = build_directions(F4Input.model_validate(data), ctx, options=options)
    by_id = {r.unit_id: r for r in results}
    assert by_id[UNIT_INVENTIVE].candidates  # order 1이 앞이라 처리됨
    assert by_id[UNIT_CLARITY].status.reason == UnverifiedReason.LIMIT_REACHED


def test_둘째_묶음만_방향_호출이_실패하면_실행_이유는_not_extracted():
    ctx, _ = _ctx(
        directions=[ONE, BAD, BAD],
        opinions=["opinion_inventive"],
        amendments=["amendment_inventive"],
    )
    out = run_f4(_case(), ctx=ctx)
    assert out.status.reason == UnverifiedReason.NOT_EXTRACTED
