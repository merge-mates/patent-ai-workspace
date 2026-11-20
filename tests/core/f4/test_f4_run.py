"""run_f4 한 바퀴와 누락 검사 테스트: 가짜 사건(fixture) + 가짜 전송층. 진짜 모델 호출 없음.

기대값은 구현 계획 C4, design_f4.md 2·3·4절, product.md 5절 F4 5·7번에서 가져왔다.
"""

import copy
import json
import logging
from pathlib import Path

import pytest

from patent_ai.core.f4_response_draft.coverage import unchecked_rejections, uncovered
from patent_ai.core.f4_response_draft.inputs import F4Input
from patent_ai.core.f4_response_draft.result import F4Output
from patent_ai.core.f4_response_draft.run import run_f4
from patent_ai.core.llm.errors import ModelOutputInvalid
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.common import Flag, StatusValue
from patent_ai.core.schemas.oa_result import OAResult, build_rejection

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "f4"
UNIT_INVENTIVE = "oa_1:29-2:c1"
UNIT_CLARITY = "oa_1:42-4-2:c2"
OK = {"value": "confirmed", "checked": "원문 대조"}


def _case_data() -> dict:
    data = json.loads((FIXTURES / "case_basic.json").read_text("utf-8"))
    data["spec"] = json.loads((FIXTURES / "spec_basic.pages.json").read_text("utf-8"))
    return data


def _confirmed_legal(unit_id: str, rejection: int) -> dict:
    """F2가 근거를 다 확인한 법률 근거 묶음 (만든 값). 안쪽 표시가 비는 사건을 만들 때 쓴다."""
    source = {
        "source_kind": "statute",
        "identifier": "만든 조문",
        "evidence": {"document_id": "law_1", "raw_text": "만든 조문 글자", "edition": "2099-01-01"},
        "status": OK,
    }
    claim = {
        "no": 1,
        "text": "만든 주장",
        "sources": [source],
        "status": {"value": "confirmed", "checked": "모든 근거 원문 대조"},
    }
    return {
        "bundle_id": f"lb:{unit_id}",
        "unit_id": unit_id,
        "oa_id": "oa_1",
        "rejection": rejection,
        "question": {
            "text": "만든 질문",
            "source": "oa_rejection",
            "as_of": None,
            "as_of_source": "none",
            "source_kinds": ["statute"],
        },
        "checked_on": "2099-02-01",
        "claims": [claim],
        "status": {"value": "confirmed", "checked": "모든 주장 근거 확인"},
    }


def _clean_case() -> dict:
    """앞 단계가 모두 확인됨인 사건: 안쪽에서 올라오는 직접 검토 표시가 없다."""
    data = _case_data()
    data["legal"] = [_confirmed_legal(UNIT_INVENTIVE, 1), _confirmed_legal(UNIT_CLARITY, 2)]
    return data


def _answer(name: str) -> dict:
    return json.loads((FIXTURES / "llm" / f"{name}.json").read_text("utf-8"))


def _text(answer: dict) -> TransportResponse:
    return TransportResponse(json.dumps(answer, ensure_ascii=False), 100, 50)


def _transport(directions, opinions, amendments) -> FakeTransport:
    def answers(items):
        return [_text(_answer(x) if isinstance(x, str) else x) for x in items]

    return FakeTransport(
        {
            "f4.direction": answers(directions),
            "f4.opinion": answers(opinions),
            "f4.amendment": answers(amendments),
        }
    )


def _run(
    data: dict | None = None,
    directions=("direction_inventive", "direction_clarity"),
    opinions=("opinion_inventive", "opinion_clarity"),
    amendments=("amendment_inventive", "amendment_clarity"),
):
    transport = _transport(directions, opinions, amendments)
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    out = run_f4(F4Input.model_validate(data or _case_data()), ctx=ctx)
    return out, transport


# ---- 한 바퀴 ----
def test_한_바퀴를_돌면_방향_후보와_초안이_한데_나온다():
    out, transport = _run()
    assert isinstance(out, F4Output) and out.oa_id == "oa_1"
    assert [d.unit_id for d in out.directions] == [UNIT_INVENTIVE, UNIT_CLARITY]
    assert [s.key for s in out.drafts.opinion] == [
        "case_info",
        "points",
        "response",
        "amendment",
        "closing",
    ]
    assert [c.claim for c in out.drafts.claims] == [1, 2]
    assert [(b.unit_id, b.candidate_id) for b in out.drafts.based_on] == [
        (d.unit_id, d.selection.candidate_id) for d in out.directions
    ]
    assert out.held_units == [] and out.unsupported_rejections == [] and out.uncovered == []
    # 순서: 방향 → 의견서 → 보정
    assert [c["step"] for c in transport.calls] == ["f4.direction"] * 2 + ["f4.opinion"] * 2 + [
        "f4.amendment"
    ] * 2


def test_결과_status는_안쪽에서_가장_나쁜_값():
    out, _ = _run()
    # F2가 아직 없어 방향 후보·초안이 모두 확인되지 않음
    assert out.status.value == StatusValue.UNVERIFIED
    assert all(d.status.value == StatusValue.UNVERIFIED for d in out.directions)
    assert out.drafts.status.value == StatusValue.UNVERIFIED


def test_결과는_JSON으로_왕복해도_같다():
    out, _ = _run()
    assert F4Output.model_validate(json.loads(out.model_dump_json())) == out


def test_앞_단계가_모두_확인됨이면_결과도_확인됨이고_검토_표시가_없다():
    out, _ = _run(_clean_case())
    assert out.status.value == StatusValue.CONFIRMED
    assert out.flags == []
    assert out.coverage_unchecked == []


# ---- 누락 검사: 모든 거절이유 × 모든 대상 청구항 ----
def _oa(data: dict) -> OAResult:
    return OAResult.model_validate(data["oa"])


def test_판단_단위가_대상_청구항을_다_덮으면_누락이_없다():
    inp = F4Input.model_validate(_case_data())
    assert uncovered(inp.oa, inp.units) == []


def test_판단_단위가_덮지_않은_청구항은_거절이유와_함께_나온다():
    data = _case_data()
    data["units"][0]["claims"] = [1]  # 거절이유 1의 대상은 청구항 1·2인데 묶음은 1만
    inp = F4Input.model_validate(data)
    # 청구항 2는 거절이유 2(명확성) 묶음에 있지만 거절이유 1에서는 빠졌다
    assert uncovered(inp.oa, inp.units) == [(1, 2)]


def test_판단_단위가_하나도_없으면_모든_대상_청구항이_누락():
    inp = F4Input.model_validate(_case_data())
    assert uncovered(inp.oa, []) == [(1, 1), (1, 2), (2, 2)]


def test_누락이_있으면_결과에_남기고_경고한다(caplog):
    data = _clean_case()  # 안쪽 표시가 없는 사건이라, 표시는 누락 때문에 새로 붙은 것
    data["units"][0]["claims"] = [1]
    with caplog.at_level(logging.WARNING):
        out, _ = _run(data)
    assert out.uncovered == [(1, 2)]
    assert out.flags == [Flag.NEEDS_HUMAN_REVIEW]
    assert "누락" in caplog.text


def _claims_unread(data: dict) -> dict:
    """거절이유 2의 대상 청구항을 못 읽은 OA (값 없음 + 확인되지 않음)."""
    data = copy.deepcopy(data)
    bad = {"value": "unverified", "reason": "not_extracted"}
    data["oa"]["rejections"][1]["claims"] = {"value": None, "status": bad}
    data["oa"]["rejections"][1]["status"] = bad
    data["oa"]["status"] = bad
    return data


def test_대상_청구항을_못_읽은_거절이유는_누락_검사를_못_했다고_남긴다(caplog):
    with caplog.at_level(logging.WARNING):
        out, _ = _run(_claims_unread(_clean_case()))
    assert out.uncovered == []  # 검사를 못 한 것이지 누락이 없다는 뜻이 아니다
    assert out.coverage_unchecked == [2]
    assert out.flags == [Flag.NEEDS_HUMAN_REVIEW]
    assert "검사하지 못함" in caplog.text


def test_대상_청구항을_못_읽은_거절이유_번호를_따로_낸다():
    inp = F4Input.model_validate(_claims_unread(_case_data()))
    assert unchecked_rejections(inp.oa) == [2]
    assert unchecked_rejections(F4Input.model_validate(_case_data()).oa) == []


# ---- 지원 안 하는 거절이유 ----
def _with_unsupported(data: dict) -> dict:
    """조문은 확인됐지만 지원 표에 없는 거절이유 3을 더한 사건."""

    def v(value, raw, page):
        return {"value": value, "raw_text": raw, "page": page, "status": OK}

    extra = build_rejection(
        document_id="d_1",
        no=3,
        article=v("45", "특허법 제45조", 3),
        supported=False,
        claims=v([1, 2, 3], "제1항 내지 제3항", 3),
        citations=[],
        examiner_reasoning=v("하나의 발명 범위를 벗어난다고 봄", "청구항 3은 단일성이 없습니다", 3),
        flags=[Flag.NEEDS_HUMAN_REVIEW],
    )
    data = copy.deepcopy(data)
    data["oa"]["rejections"].append(extra.model_dump(mode="json"))
    return data


def test_지원_안_하는_거절이유는_번호를_남기고_status는_나빠지지_않는다():
    plain, _ = _run(_clean_case())
    assert plain.flags == []
    out, _ = _run(_with_unsupported(_clean_case()))
    assert out.unsupported_rejections == [3]
    assert out.flags == [Flag.NEEDS_HUMAN_REVIEW]  # 지원 안 하는 거절이유 때문에 새로 붙음
    assert out.status == plain.status  # 지원 안 하는 거절이유 때문에 달라지지 않음
    assert out.uncovered == []  # 지원 안 하는 거절이유의 청구항은 누락으로 세지 않는다


# ---- 확신 낮음 ----
def _low_inventive() -> dict:
    low = copy.deepcopy(_answer("direction_low"))
    for c in low["candidates"]:
        c["per_rejection"] = [{"rejection": 1, "response": "직접 판단 필요"}]
        c["amendment_core"] = [{"claim": 1, "kind": "limit"}] if c["rebuttal"] is None else []
        if c["rebuttal"]:
            c["rebuttal"]["type"] = "difference"
    return low


def test_모든_묶음이_확신_낮음이면_초안_없이_보류한다(caplog):
    with caplog.at_level(logging.WARNING):
        out, transport = _run(
            directions=(_low_inventive(), "direction_low"), opinions=(), amendments=()
        )
    assert out.drafts is None
    assert out.held_units == [UNIT_INVENTIVE, UNIT_CLARITY]
    assert Flag.NEEDS_HUMAN_JUDGMENT in out.flags
    assert out.status.value == StatusValue.UNVERIFIED
    assert [c["step"] for c in transport.calls] == ["f4.direction"] * 2
    assert "보류" in caplog.text


def test_한_묶음만_확신_낮음이면_나머지는_진행한다():
    out, _ = _run(
        directions=("direction_inventive", "direction_low"),
        opinions=("opinion_inventive",),
        amendments=("amendment_inventive",),
    )
    assert out.held_units == [UNIT_CLARITY]
    assert [b.unit_id for b in out.drafts.based_on] == [UNIT_INVENTIVE]
    held = next(c for c in out.drafts.claims if c.claim == 2)
    assert held.ai_text is None and held.held_reason


# ---- 실패는 숨기지 않는다 ----
def test_단계가_실패하면_예외가_그대로_올라온다():
    bad = copy.deepcopy(_answer("opinion_inventive"))
    bad["response"] = " "
    with pytest.raises(ModelOutputInvalid):
        _run(opinions=(bad, bad))
