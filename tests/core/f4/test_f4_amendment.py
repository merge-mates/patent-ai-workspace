"""F4 보정 청구항 초안 단계 테스트: 가짜 사건·가짜 명세서(fixture) + 가짜 전송층.

진짜 모델 호출 없음.

기대값은 구현 계획 C3, design_f4.md 3·5·8절, 스키마 검사(drafts.py),
product.md 5절 F4 2·4번에서 가져왔다.
"""

import copy
import json
import logging
from pathlib import Path

import pytest

from patent_ai.core.f4_response_draft.amendment import (
    LEGALITY_NOTICE,
    STEP,
    assemble_drafts,
    build_amendments,
    diff_claim,
)
from patent_ai.core.f4_response_draft.directions import STEP as DIRECTION_STEP
from patent_ai.core.f4_response_draft.directions import build_directions
from patent_ai.core.f4_response_draft.inputs import F4Input
from patent_ai.core.f4_response_draft.opinion import STEP as OPINION_STEP
from patent_ai.core.f4_response_draft.opinion import build_opinion
from patent_ai.core.llm.config import load_step_config
from patent_ai.core.llm.errors import ModelOutputInvalid
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.common import Flag, Origin, StatusValue, UnverifiedReason
from patent_ai.core.schemas.drafts import Drafts

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "f4"
UNIT_INVENTIVE = "oa_1:29-2:c1"
UNIT_CLARITY = "oa_1:42-4-2:c2"


def _case(with_spec: bool = True) -> F4Input:
    data = json.loads((FIXTURES / "case_basic.json").read_text("utf-8"))
    if with_spec:
        data["spec"] = json.loads((FIXTURES / "spec_basic.pages.json").read_text("utf-8"))
    return F4Input.model_validate(data)


def _answer(name: str) -> dict:
    return json.loads((FIXTURES / "llm" / f"{name}.json").read_text("utf-8"))


def _text(answer: dict) -> TransportResponse:
    return TransportResponse(json.dumps(answer, ensure_ascii=False), 100, 50)


def _run(
    amendments: list,
    *,
    directions: tuple = ("direction_inventive", "direction_clarity"),
    opinions: tuple = ("opinion_inventive", "opinion_clarity"),
    inp: F4Input | None = None,
):
    """방향 → 의견서 → 보정 순서로 가짜 전송층을 돌린다. 이름이 아닌 dict는 그대로 답으로 쓴다."""

    def answers(items):
        return [_text(_answer(x) if isinstance(x, str) else x) for x in items]

    transport = FakeTransport(
        {
            DIRECTION_STEP: answers(directions),
            OPINION_STEP: answers(opinions),
            STEP: answers(amendments),
        }
    )
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    inp = inp or _case()
    found = build_directions(inp, ctx)
    opinion = build_opinion(inp, found, ctx)
    part = build_amendments(inp, found, opinion, ctx)
    return part, transport, opinion


def _basic(**kw):
    return _run(["amendment_inventive", "amendment_clarity"], **kw)


def _calls(transport) -> list[dict]:
    return [c for c in transport.calls if c["step"] == STEP]


# ---- 기본: 바뀐 청구항마다 초안과 명세서 근거 위치 ----
def test_바뀐_청구항마다_보정_초안과_명세서_근거_위치가_있다():
    part, _, _ = _basic()
    inp = _case()
    before = {c.claim: c.text for c in inp.claims_text}
    assert [c.claim for c in part.claims] == [1, 2]
    assert [c.unit_id for c in part.claims] == [UNIT_INVENTIVE, UNIT_CLARITY]
    for c, name in zip(part.claims, ("amendment_inventive", "amendment_clarity"), strict=True):
        given = _answer(name)["claims"][0]
        assert c.before == before[c.claim]  # OA 당시 청구항 글자
        assert c.ai_text == given["text"] and c.held_reason is None
        assert c.origin == Origin.AI_GENERATED and c.human_text is None
        (basis,) = c.spec_basis
        assert basis.document_id == "spec_1"
        assert (basis.page, basis.location, basis.raw_text) == (
            given["spec_basis"][0]["page"],
            given["spec_basis"][0]["location"],
            given["spec_basis"][0]["raw_text"],
        )
    assert all(s.value == StatusValue.CONFIRMED for s in part.statuses)
    assert part.flags == [] and part.held_units == []


def test_호출_순서는_방향_의견서_보정():
    _, transport, _ = _basic()
    assert [c["step"] for c in transport.calls] == [
        "f4.direction",
        "f4.direction",
        "f4.opinion",
        "f4.opinion",
        "f4.amendment",
        "f4.amendment",
    ]


# ---- 근거 위치를 못 찾음: 초안은 남기고 근거만 비운다 ----
def _with_basis(name: str, **basis) -> dict:
    answer = copy.deepcopy(_answer(name))
    answer["claims"][0]["spec_basis"][0].update(basis)
    return answer


@pytest.mark.parametrize(
    "basis",
    [
        {"raw_text": "덮개는 금으로 만든다"},  # 명세서에 없는 글자 (지어낸 근거)
        {"page": 1},  # 글자는 있지만 그 쪽에 없음
        {"page": 9},  # 없는 쪽
    ],
)
def test_명세서에_없는_근거는_버리고_확인되지_않음으로_둔다(basis, caplog):
    with caplog.at_level(logging.WARNING):
        part, _, _ = _run([_with_basis("amendment_inventive", **basis), "amendment_clarity"])
    first, second = part.claims
    assert first.ai_text and first.spec_basis == []  # 초안은 남고 근거만 빠짐
    assert second.spec_basis  # 다른 청구항은 그대로
    assert part.statuses[0].value == StatusValue.UNVERIFIED
    assert part.statuses[0].reason == UnverifiedReason.EVIDENCE_REJECTED
    assert Flag.NEEDS_HUMAN_REVIEW in part.flags
    assert "근거" in caplog.text


def test_모델이_근거를_하나도_안_줘도_확인되지_않음():
    answer = copy.deepcopy(_answer("amendment_inventive"))
    answer["claims"][0]["spec_basis"] = []
    part, _, _ = _run([answer, "amendment_clarity"])
    assert part.claims[0].spec_basis == []
    assert part.statuses[0].reason == UnverifiedReason.EVIDENCE_REJECTED
    assert Flag.NEEDS_HUMAN_REVIEW in part.flags


def test_명세서가_없으면_근거_위치는_body_missing으로_보류():
    part, _, _ = _basic(inp=_case(with_spec=False))
    assert [c.claim for c in part.claims] == [1, 2]
    for c, s in zip(part.claims, part.statuses, strict=True):
        assert c.ai_text and c.spec_basis == []
        assert (s.value, s.reason) == (StatusValue.UNVERIFIED, UnverifiedReason.BODY_MISSING)
    assert Flag.NEEDS_HUMAN_REVIEW in part.flags


# ---- 확신 낮음: 그 묶음 청구항만 보류 ----
def test_확신_낮은_묶음의_청구항은_초안_없이_보류하고_모델을_부르지_않는다():
    part, transport, _ = _run(
        ["amendment_inventive"],
        directions=("direction_inventive", "direction_low"),
        opinions=("opinion_inventive",),
    )
    assert len(_calls(transport)) == 1  # 진보성 묶음만
    made, held = part.claims
    assert (made.claim, made.unit_id) == (1, UNIT_INVENTIVE) and made.ai_text
    assert (held.claim, held.unit_id) == (2, UNIT_CLARITY)
    assert held.ai_text is None and held.held_reason and held.spec_basis == []
    assert part.held_units == [UNIT_CLARITY]


def _argue_only() -> dict:
    only = copy.deepcopy(_answer("direction_inventive"))
    only["candidates"] = only["candidates"][1:]
    only["candidates"][0]["rank"] = 1
    return only


def test_보정이_없는_방향은_모델을_부르지_않고_청구항도_만들지_않는다():
    opinion = copy.deepcopy(_answer("opinion_inventive"))
    opinion["amendment"] = None
    part, transport, _ = _run(
        ["amendment_clarity"],
        directions=(_argue_only(), "direction_clarity"),
        opinions=(opinion, "opinion_clarity"),
    )
    assert len(_calls(transport)) == 1
    assert [c.claim for c in part.claims] == [2]


# ---- 출력 검사 ----
def _clarity_with_claim(claim: int) -> dict:
    answer = copy.deepcopy(_answer("amendment_clarity"))
    answer["claims"][0]["claim"] = claim
    return answer


def test_묶음_밖_청구항을_고치면_출력_검사_실패_뒤_한_번_다시_부른다():
    part, transport, _ = _run(["amendment_inventive", _clarity_with_claim(3), "amendment_clarity"])
    assert len(_calls(transport)) == 3
    assert [c.claim for c in part.claims] == [1, 2]


def test_다시_불러도_묶음_밖이면_실패가_그대로_드러난다():
    with pytest.raises(ModelOutputInvalid):
        _run(["amendment_inventive", _clarity_with_claim(3), _clarity_with_claim(3)])


def test_고른_방향이_고치기로_한_청구항이_답에_없으면_출력_검사_실패():
    empty = {"claims": []}
    with pytest.raises(ModelOutputInvalid):
        _run([empty, empty])


def test_보정_글자가_비면_출력_검사_실패():
    blank = copy.deepcopy(_answer("amendment_inventive"))
    blank["claims"][0]["text"] = "  "
    with pytest.raises(ModelOutputInvalid):
        _run([blank, blank])


# ---- 한 청구항이 여러 묶음에 걸침 ----
def test_앞선_묶음이_가진_청구항을_뒤_묶음이_덮어쓰지_않는다(caplog):
    both = copy.deepcopy(_answer("amendment_inventive"))
    extra = copy.deepcopy(_answer("amendment_clarity")["claims"][0])
    extra["text"] = "진보성 묶음이 쓴 청구항 2 초안"
    both["claims"].append(extra)  # 진보성 묶음(order 1)이 청구항 2도 고침
    with caplog.at_level(logging.WARNING):
        part, _, _ = _run([both, "amendment_clarity"])
    nums = [c.claim for c in part.claims]
    assert nums == [1, 2] and len(set(nums)) == len(nums)  # 번호 중복 없음
    second = part.claims[1]
    assert second.unit_id == UNIT_INVENTIVE and second.ai_text == "진보성 묶음이 쓴 청구항 2 초안"
    assert Flag.NEEDS_HUMAN_REVIEW in part.flags
    assert UNIT_CLARITY in caplog.text


# ---- Drafts로 묶기 ----
def test_의견서와_보정_청구항을_Drafts_하나로_묶는다():
    part, _, opinion = _basic()
    drafts = assemble_drafts("oa_1", opinion, part)
    assert isinstance(drafts, Drafts)
    assert drafts.claims == part.claims and drafts.opinion == opinion.sections
    assert drafts.origin == Origin.AI_GENERATED
    # 법률 근거가 아직 확인되지 않음이라 초안 전체도 확인됨이 못 됨
    assert drafts.status.value == StatusValue.UNVERIFIED


def test_근거를_못_찾은_표시는_Drafts에도_남는다():
    part, _, opinion = _run(
        [_with_basis("amendment_inventive", raw_text="덮개는 금으로 만든다"), "amendment_clarity"]
    )
    drafts = assemble_drafts("oa_1", opinion, part)
    assert drafts.status.value == StatusValue.UNVERIFIED
    assert Flag.NEEDS_HUMAN_REVIEW in drafts.flags


# ---- 바뀐 부분 (저장하지 않고 비교만) ----
def test_바뀐_부분은_앞뒤_글자를_비교해_낸다():
    assert diff_claim("적당한 간격을 둔다", "좁은 간격을 둔다") == [
        {"op": "replace", "before": "적당한", "after": "좁은"},
        {"op": "equal", "before": " 간격을 둔다", "after": " 간격을 둔다"},
    ]
    assert diff_claim("센서 장치.", "센서와 덮개 장치.") == [
        {"op": "equal", "before": "센서", "after": "센서"},
        {"op": "insert", "before": "", "after": "와 덮개"},
        {"op": "equal", "before": " 장치.", "after": " 장치."},
    ]
    assert diff_claim("가나다", "가다") == [
        {"op": "equal", "before": "가", "after": "가"},
        {"op": "delete", "before": "나", "after": ""},
        {"op": "equal", "before": "다", "after": "다"},
    ]


def test_바뀐_부분을_이으면_앞뒤_글자가_그대로_나온다():
    part, _, _ = _basic()
    for c in part.claims:
        parts = diff_claim(c.before, c.ai_text)
        assert "".join(p["before"] for p in parts) == c.before
        assert "".join(p["after"] for p in parts) == c.ai_text
        assert any(p["op"] != "equal" for p in parts)


def test_보류된_청구항은_바뀐_부분이_없다():
    assert diff_claim("가나다", None) == []


def test_적법성을_판단하지_않았다는_문구가_상수로_있다():
    assert "적법성" in LEGALITY_NOTICE and "판단하지 않" in LEGALITY_NOTICE


# ---- 설정 ----
def test_저장소_설정의_보정_단계_값():
    cfg = load_step_config("f4.amendment")
    assert (cfg.model, cfg.effort, cfg.max_tokens) == ("claude-haiku-5-5", "medium", 64000)
    assert cfg.prompt == "prompts/f4/amendment.md"
    assert cfg.max_model_calls == load_step_config("f4.direction").max_model_calls
