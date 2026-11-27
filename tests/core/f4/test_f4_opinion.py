"""F4 의견서 초안 단계 테스트: 가짜 사건(fixture) + 가짜 전송층(사람이 쓴 답). 진짜 모델 호출 없음.

기대값은 구현 계획 C2, `docs/features/F4/design.md`
2절 ②·3-2절(선택 값·의견서 칸), 스키마 검사(drafts.py),
product.md 5절 F4 2·3번에서 가져왔다.
"""

import copy
import json
import logging
from pathlib import Path

import pytest

from patent_ai.core.f4_response_draft.amendment import STEP as AMENDMENT_STEP
from patent_ai.core.f4_response_draft.amendment import assemble_drafts, build_amendments
from patent_ai.core.f4_response_draft.directions import STEP as DIRECTION_STEP
from patent_ai.core.f4_response_draft.directions import build_directions
from patent_ai.core.f4_response_draft.inputs import F4Input
from patent_ai.core.f4_response_draft.opinion import STEP, build_opinion, drafts_from_opinion
from patent_ai.core.llm.config import load_step_config
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.common import Flag, Origin, StatusValue, UnverifiedReason
from patent_ai.core.schemas.direction import DirectionCandidates
from patent_ai.core.schemas.drafts import Drafts, OpinionKey

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "f4"
UNIT_INVENTIVE = "oa_1:29-2:c1"
UNIT_CLARITY = "oa_1:42-4-2:c2"


def _case() -> F4Input:
    return F4Input.model_validate_json((FIXTURES / "case_basic.json").read_text("utf-8"))


def _answer(name: str) -> dict:
    return json.loads((FIXTURES / "llm" / f"{name}.json").read_text("utf-8"))


def _text(answer: dict) -> TransportResponse:
    return TransportResponse(json.dumps(answer, ensure_ascii=False), 100, 50)


def _run(
    opinions: list, directions: tuple[str, str] = ("direction_inventive", "direction_clarity")
):
    """방향 후보 단계 → 의견서 단계를 가짜 전송층으로 돌린다. opinions는 의견서 답(부르는 순서)."""
    transport = FakeTransport(
        {DIRECTION_STEP: [_text(_answer(d)) for d in directions], STEP: opinions}
    )
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    inp = _case()
    found = build_directions(inp, ctx)
    part = build_opinion(inp, found, ctx)
    calls = [c for c in transport.calls if c["step"] == STEP]
    return part, calls, found


def _basic():
    return _run([_text(_answer("opinion_inventive")), _text(_answer("opinion_clarity"))])


# ---- 구성과 AI 원문 ----
def test_의견서_칸은_정해진_순서이고_AI_원문이_비지_않는다():
    part, calls, _ = _basic()
    assert len(calls) == 2  # 묶음마다 한 번
    # 변리사 확인 사항(review)은 의견서만 흐름(opinion_v2)에서 메모가 있을 때만 붙는다
    assert [s.key for s in part.sections] == [k for k in OpinionKey if k != OpinionKey.REVIEW]
    for s in part.sections:
        assert s.ai_text.strip() and s.title.strip()


def test_초안은_AI_생성으로_표시되고_사람이_고친_글은_없다():
    part, _, _ = _basic()
    for s in part.sections:
        assert s.origin == Origin.AI_GENERATED and s.human_text is None


def test_묶음_둘의_칸은_order_순으로_이어_붙고_사건_정보와_마무리는_첫_묶음_것():
    part, _, _ = _basic()
    first, second = _answer("opinion_inventive"), _answer("opinion_clarity")
    text = {s.key: s.ai_text for s in part.sections}
    for key in ("points", "response", "amendment"):
        assert text[key] == first[key] + "\n\n" + second[key]
    assert text["case_info"] == first["case_info"]
    assert text["closing"] == first["closing"]


def test_어느_후보로_만들었는지_남는다():
    part, _, found = _basic()
    assert [(b.unit_id, b.candidate_id) for b in part.based_on] == [
        (r.unit_id, r.selection.candidate_id) for r in found
    ]
    assert part.held_units == []


# ---- 보류 묶음에서 사람이 고른 경로 ----
def test_보류_묶음에서_사람이_고른_후보로_의견서와_보정이_만들어진다():
    # 확신 낮은 보정 묶음(clarity)은 AI 기본 선택이 없어 보류된다. 사람이 그중 보정 후보를 고른다
    transport = FakeTransport(
        {
            DIRECTION_STEP: [
                _text(_answer("direction_inventive")),
                _text(_answer("direction_low")),
            ],
            STEP: [_text(_answer("opinion_inventive")), _text(_answer("opinion_clarity"))],
            AMENDMENT_STEP: [
                _text(_answer("amendment_inventive")),
                _text(_answer("amendment_clarity")),
            ],
        }
    )
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    inp = _case()
    found = build_directions(inp, ctx)
    held = next(r for r in found if r.unit_id == UNIT_CLARITY)
    assert held.selection is None  # AI 기본 선택 없음
    picked = next(c for c in held.candidates if c.coarse == "amend_only")
    other = next(c for c in held.candidates if c.candidate_id != picked.candidate_id)
    # 사람 선택: 화면이 selection만 human_selected로 채워 돌려준 결과
    data = held.model_dump(mode="json")
    data["selection"] = {"candidate_id": picked.candidate_id, "origin": "human_selected"}
    found = [DirectionCandidates.model_validate(data) if r is held else r for r in found]

    opinion = build_opinion(inp, found, ctx)
    amendment = build_amendments(inp, found, opinion, ctx)

    # (1) 고른 후보만 의견서·보정 프롬프트에 들어간다
    for step in (STEP, AMENDMENT_STEP):
        prompt = [c for c in transport.calls if c["step"] == step][1]["prompt"]
        assert picked.name in prompt
        assert other.name not in prompt
    # (2) 어느 묶음·후보로 만들었는지 남는다
    assert (UNIT_CLARITY, picked.candidate_id) in [
        (b.unit_id, b.candidate_id) for b in opinion.based_on
    ]
    # (3) 보정 초안이 고른 후보의 보정 청구항(2항)으로 만들어진다
    claim2 = next(c for c in amendment.claims if c.claim == 2)
    assert claim2.ai_text == _answer("amendment_clarity")["claims"][0]["text"]
    assert claim2.held_reason is None
    # (3') 의견서·보정을 묶은 초안에도 그 묶음·후보가 남는다
    drafts = assemble_drafts(inp.oa.oa_id, opinion, amendment)
    assert (UNIT_CLARITY, picked.candidate_id) in [
        (b.unit_id, b.candidate_id) for b in drafts.based_on
    ]
    # (4) 보류가 아니다
    assert opinion.held_units == [] and amendment.held_units == []
    assert len(opinion.based_on) == 2


# ---- 고른 방향으로만 ----
def test_고르지_않은_후보는_프롬프트에_들어가지_않는다():
    _, calls, found = _basic()
    chosen, other = found[0].candidates  # 1등(선택됨), 2등(고르지 않음)
    prompt = calls[0]["prompt"]
    assert chosen.name in prompt and chosen.reason in prompt
    assert other.name not in prompt and other.reason not in prompt
    assert other.rebuttal.summary not in prompt
    assert all(p.response not in prompt for p in other.per_rejection)


# ---- 확신 낮음: 그 묶음만 보류 ----
def test_확신_낮은_묶음은_모델을_부르지_않고_보류한다():
    part, calls, _ = _run(
        [_text(_answer("opinion_inventive"))], ("direction_inventive", "direction_low")
    )
    assert len(calls) == 1  # 진보성 묶음만
    assert part.held_units == [UNIT_CLARITY]
    assert [b.unit_id for b in part.based_on] == [UNIT_INVENTIVE]
    assert Flag.NEEDS_HUMAN_JUDGMENT in part.flags
    text = {s.key: s.ai_text for s in part.sections}
    assert text["points"] == _answer("opinion_inventive")["points"]


def test_직접_쓴_방향을_고른_묶음은_AI가_초안을_만들지_않고_보류한다(caplog):
    transport = FakeTransport(
        {
            DIRECTION_STEP: [_text(_answer(d)) for d in ("direction_inventive", "direction_low")],
            STEP: [_text(_answer("opinion_inventive"))],
        }
    )
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    inp = _case()
    found = build_directions(inp, ctx)
    held = next(r for r in found if r.unit_id == UNIT_CLARITY)
    data = held.model_dump(mode="json")
    data["selection"] = {"written_direction": "사람이 쓴 방향", "origin": "human_written"}
    found = [DirectionCandidates.model_validate(data) if r is held else r for r in found]

    with caplog.at_level(logging.WARNING):
        part = build_opinion(inp, found, ctx)

    assert "사람이 쓴 방향" in caplog.text
    assert part.held_units == [UNIT_CLARITY]
    assert [b.unit_id for b in part.based_on] == [UNIT_INVENTIVE]


def test_모든_묶음이_확신_낮음이면_칸이_없고_초안도_없다(caplog):
    low = copy.deepcopy(_answer("direction_low"))
    for c in low["candidates"]:  # 진보성 묶음용으로 거절이유 번호·청구항·반박 유형을 맞춘다
        c["per_rejection"] = [{"rejection": 1, "response": "직접 판단 필요"}]
        c["amendment_core"] = [{"claim": 1, "kind": "limit"}] if c["rebuttal"] is None else []
        if c["rebuttal"]:
            c["rebuttal"]["type"] = "difference"
    transport = FakeTransport(
        {DIRECTION_STEP: [_text(low), _text(_answer("direction_low"))], STEP: []}
    )
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    inp = _case()
    found = build_directions(inp, ctx)
    with caplog.at_level(logging.WARNING):
        part = build_opinion(inp, found, ctx)
        assert drafts_from_opinion("oa_1", part) is None
    assert part.sections == [] and part.held_units == [UNIT_INVENTIVE, UNIT_CLARITY]
    assert all(c["step"] != STEP for c in transport.calls)
    assert "보류" in caplog.text


# ---- 출력 검사 ----
def _blank(name: str, key: str) -> dict:
    bad = copy.deepcopy(_answer(name))
    bad[key] = "  \n"
    return bad


def test_빈_글이_오면_한_번_다시_부른다():
    part, calls, _ = _run(
        [
            _text(_blank("opinion_inventive", "response")),
            _text(_answer("opinion_inventive")),
            _text(_answer("opinion_clarity")),
        ]
    )
    assert len(calls) == 3
    assert all(s.ai_text.strip() for s in part.sections)


def test_다시_불러도_비면_그_묶음은_보류로_드러난다():
    bad = _text(_blank("opinion_inventive", "response"))
    part, _, _ = _run([bad] * 4)  # 묶음 둘이 모두 실패: 단계 실패가 아니라 모두 보류
    assert part.sections == [] and part.held_units == [UNIT_INVENTIVE, UNIT_CLARITY]
    assert set(part.failed_reasons) == {UNIT_INVENTIVE, UNIT_CLARITY}
    assert "ModelOutputInvalid" in part.failed_reasons[UNIT_INVENTIVE]


def test_보정이_있는_방향인데_보정_설명이_없으면_출력_검사_실패로_그_묶음_보류():
    bad = copy.deepcopy(_answer("opinion_inventive"))
    bad["amendment"] = None
    part, _, _ = _run([_text(bad)] * 4)
    assert part.sections == [] and UNIT_INVENTIVE in part.failed_reasons


def _argue_only_direction() -> dict:
    """진보성 묶음에서 보정 없이 반박하는 후보 하나만 1등인 답."""
    only = copy.deepcopy(_answer("direction_inventive"))
    only["candidates"] = only["candidates"][1:]
    only["candidates"][0]["rank"] = 1
    return only


def _run_argue_only(opinion: dict):
    transport = FakeTransport(
        {
            DIRECTION_STEP: [_text(_argue_only_direction()), _text(_answer("direction_low"))],
            STEP: [_text(opinion), _text(opinion)],
        }
    )
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    inp = _case()
    return build_opinion(inp, build_directions(inp, ctx), ctx)


def test_보정이_없는_방향이면_보정_설명_칸을_만들지_않는다():
    answer = copy.deepcopy(_answer("opinion_inventive"))
    answer["amendment"] = None
    part = _run_argue_only(answer)
    assert [s.key for s in part.sections] == ["case_info", "points", "response", "closing"]


def test_보정이_없는_방향인데_보정_설명을_쓰면_출력_검사_실패로_그_묶음_보류():
    part = _run_argue_only(_answer("opinion_inventive"))
    assert part.sections == [] and UNIT_INVENTIVE in part.failed_reasons


def test_방향_후보_결과가_없는_묶음이_있으면_멈춘다():
    transport = FakeTransport({STEP: []})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    with pytest.raises(ValueError, match=UNIT_INVENTIVE):
        build_opinion(_case(), [], ctx)
    assert transport.calls == []


# ---- status ----
def test_법률_근거가_빈_묶음이면_초안은_확인됨이_될_수_없다():
    part, _, _ = _basic()
    assert part.status.value == StatusValue.UNVERIFIED
    assert part.status.reason == UnverifiedReason.INPUT_UNVERIFIED
    assert Flag.NEEDS_HUMAN_REVIEW in part.flags


def test_후보가_확인됨이어도_법률_근거가_확인되지_않음이면_확인되지_않음():
    _, _, found = _basic()
    ok = {"value": "confirmed", "checked": "테스트용 확인"}
    confirmed = []
    for r in found:  # 후보·묶음 status만 확인됨으로 바꾼 방향 후보 결과
        data = r.model_dump(mode="json")
        data["status"] = ok
        for c in data["candidates"]:
            c["status"] = ok
        confirmed.append(DirectionCandidates.model_validate(data))
    transport = FakeTransport(
        {STEP: [_text(_answer("opinion_inventive")), _text(_answer("opinion_clarity"))]}
    )
    ctx = RunContext(
        run_id="r_2", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    part = build_opinion(_case(), confirmed, ctx)  # 입력 legal이 비어 빈 묶음(unverified)을 씀
    assert part.status.value == StatusValue.UNVERIFIED


def test_근거는_고른_후보의_근거만_담는다():
    part, _, found = _basic()
    expected = []
    for r in found:
        chosen = next(c for c in r.candidates if c.candidate_id == r.selection.candidate_id)
        expected += [e for e in chosen.evidence if e not in expected]
    assert part.evidence == expected


# ---- Drafts로 묶기 ----
def test_의견서만으로_Drafts를_만들_수_있다():
    part, _, _ = _basic()
    drafts = drafts_from_opinion("oa_1", part)
    assert isinstance(drafts, Drafts)
    assert drafts.opinion == part.sections and drafts.claims == []
    assert drafts.based_on == part.based_on
    assert drafts.origin == Origin.AI_GENERATED
    assert drafts.status.value == StatusValue.UNVERIFIED
    assert drafts.draft_id == "dr:oa_1"


# ---- 설정 ----
def test_저장소_설정의_의견서_단계_값():
    cfg = load_step_config("f4.opinion")
    assert (cfg.model, cfg.effort, cfg.max_tokens) == ("claude-haiku-5-5", "medium", 64000)
    assert cfg.prompt == "prompts/f4/opinion.md"
    assert cfg.max_model_calls == load_step_config("f4.direction").max_model_calls


# ---- 사건 단위 의견서 (합친 흐름 실험, 이 브랜치) ----
def test_사건_단위_의견서는_모든_묶음과_청구항과_OA_글을_한_번에_넘긴다():
    from patent_ai.core.f4_response_draft.opinion import build_case_opinion

    inp = _case()
    transport = FakeTransport({STEP: [_text(_answer("opinion_inventive"))]})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    out = build_case_opinion(inp, '{"name": "보정안"}', ctx, oa_text="OA 원문 표시글")
    assert len(transport.calls) == 1  # 묶음이 둘이어도 한 번
    prompt = transport.calls[0]["prompt"]
    for unit in inp.units:
        assert unit.unit_id in prompt
    for claim in inp.claims_text:
        assert claim.text in prompt
    assert "OA 원문 표시글" in prompt and '"보정안"' in prompt
    assert out.response == _answer("opinion_inventive")["response"]
