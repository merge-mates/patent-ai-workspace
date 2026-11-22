"""F4 보정 청구항 초안 단계 테스트: 가짜 사건·가짜 명세서(fixture) + 가짜 전송층.

진짜 모델 호출 없음.

기대값은 구현 계획 C3, `docs/features/F4/design.md`
2절 ③·3-2절(보정 청구항 칸·겹침)·4절(근거 대조), 스키마 검사(drafts.py),
product.md 5절 F4 2·4번에서 가져왔다.
"""

import copy
import json
import logging
from pathlib import Path

import pytest

from patent_ai.core.f4_response_draft.amendment import (
    HELD_NO_CLAIM_TEXT,
    HELD_NO_SELECTION,
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
        {"raw_text": "막"},  # 명세서에 있지만 너무 짧아 어디든 맞는 글자
        {"raw_text": "[0015]"},  # 식별번호만
        {"raw_text": "둘 수  있 다"},  # 띄어쓰기를 빼면 하한보다 짧음
        {"raw_text": "  "},  # 빈 글자
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


def test_다시_불러도_묶음_밖이면_그_묶음만_보류로_드러난다():
    # 앞 묶음 초안은 남고, 두 번 다 틀린 묶음은 받지 않고 청구항 자리에 보류 이유를 남긴다
    part, _, _ = _run(["amendment_inventive", _clarity_with_claim(3), _clarity_with_claim(3)])
    assert part.held_units == [UNIT_CLARITY]
    by_claim = {c.claim: c for c in part.claims}
    assert by_claim[1].ai_text is not None
    assert by_claim[2].ai_text is None and by_claim[2].held_reason


def test_고른_방향이_고치기로_한_청구항이_답에_없으면_출력_검사_실패로_묶음_보류():
    empty = {"claims": []}
    part, _, _ = _run([empty] * 4)
    assert part.held_units == [UNIT_INVENTIVE, UNIT_CLARITY]
    assert all(
        "보정 단계" in c.held_reason and "ModelOutputInvalid" in c.held_reason for c in part.claims
    )


def test_보정_글자가_비면_출력_검사_실패로_묶음_보류():
    blank = copy.deepcopy(_answer("amendment_inventive"))
    blank["claims"][0]["text"] = "  "
    part, _, _ = _run([blank] * 4)
    assert part.held_units == [UNIT_INVENTIVE, UNIT_CLARITY]


# ---- 삭제하는 청구항 ----
def _delete_direction() -> dict:
    """진보성 묶음에서 청구항 1에 구성을 더하고 청구항 2를 삭제하는 후보 하나."""
    answer = copy.deepcopy(_answer("direction_inventive"))
    answer["candidates"] = answer["candidates"][:1]
    answer["candidates"][0]["amendment_core"].append({"claim": 2, "kind": "delete"})
    return answer


def _delete_amendment(text: str) -> dict:
    answer = copy.deepcopy(_answer("amendment_inventive"))
    answer["claims"].append({"claim": 2, "text": text, "spec_basis": []})
    return answer


def _run_delete(amendments: list):
    return _run(
        amendments,
        directions=(_delete_direction(), "direction_low"),
        opinions=("opinion_inventive",),
    )


def test_삭제하는_청구항은_삭제라고만_쓰면_근거_없이도_확인됨():
    part, _, _ = _run_delete([_delete_amendment(" (삭제) ")])
    deleted = part.claims[1]
    assert (deleted.claim, deleted.spec_basis) == (2, [])
    assert part.statuses[1].value == StatusValue.CONFIRMED
    assert "삭제" in part.statuses[1].checked  # 실제로 한 일을 적는다 (원문 대조가 아님)


def test_삭제로_표시하고_다른_글을_쓰면_출력_검사_실패_뒤_다시_부른다():
    bad = _delete_amendment("제1항에 있어서, 금으로 만든 덮개를 더 둔 가상의 센서 장치.")
    part, transport, _ = _run_delete([bad, _delete_amendment("(삭제)")])
    assert len(_calls(transport)) == 2
    assert part.claims[1].ai_text.strip() == "(삭제)"
    held, _, _ = _run_delete([bad, bad])  # 두 번 다 틀리면 그 묶음 보류
    assert UNIT_INVENTIVE in held.held_units


# ---- 한 청구항이 여러 묶음에 걸침 ----
def test_앞선_묶음이_보류여도_뒤_묶음의_실제_초안은_남는다():
    low = copy.deepcopy(_answer("direction_low"))  # 진보성 묶음(청구항 1·2)을 확신 낮음으로
    for c in low["candidates"]:
        c["per_rejection"] = [{"rejection": 1, "response": "직접 판단 필요"}]
        c["amendment_core"] = [{"claim": 1, "kind": "limit"}] if c["rebuttal"] is None else []
        if c["rebuttal"]:
            c["rebuttal"]["type"] = "difference"
    part, transport, opinion = _run(
        ["amendment_clarity"],
        directions=(low, "direction_clarity"),
        opinions=("opinion_clarity",),
    )
    assert len(_calls(transport)) == 1  # 명확성 묶음은 불렀다
    assert [c.claim for c in part.claims] == [1, 2]
    first, second = part.claims
    # 청구항 1은 보류 자리 표시, 청구항 2는 명확성 묶음이 쓴 실제 초안 (자리 표시가 막지 않는다)
    assert first.unit_id == UNIT_INVENTIVE and first.ai_text is None
    assert first.held_reason == HELD_NO_SELECTION
    assert second.unit_id == UNIT_CLARITY
    assert second.ai_text == _answer("amendment_clarity")["claims"][0]["text"]
    assert part.held_units == [UNIT_INVENTIVE]
    assert Flag.NEEDS_HUMAN_REVIEW not in part.flags  # 실제 초안끼리 겹친 것이 아니다
    # 의견서를 만든 묶음(based_on)은 보정 청구항도 갖는다 (어긋난 데이터가 아님)
    assert [b.unit_id for b in opinion.based_on] == [UNIT_CLARITY]


def test_청구항_글자가_빠진_묶음만_보류하고_이유는_그_청구항에만_붙는다():
    data = json.loads((FIXTURES / "case_basic.json").read_text("utf-8"))
    data["spec"] = json.loads((FIXTURES / "spec_basic.pages.json").read_text("utf-8"))
    data["claims_text"] = [c for c in data["claims_text"] if c["claim"] != 1]  # 청구항 1 글자 없음
    part, transport, _ = _run(["amendment_clarity"], inp=F4Input.model_validate(data))
    assert len(_calls(transport)) == 1  # 진보성 묶음은 부르지 않고, 명확성 묶음만
    first, second = part.claims
    assert (first.claim, first.unit_id, first.ai_text) == (1, UNIT_INVENTIVE, None)
    assert first.held_reason == HELD_NO_CLAIM_TEXT and first.before == ""
    # 글자가 있는 청구항 2에는 "글자 없음" 이유가 붙지 않고, 명확성 묶음의 실제 초안이 남는다
    assert (second.claim, second.unit_id) == (2, UNIT_CLARITY)
    assert second.ai_text and second.held_reason is None
    assert part.held_units == [UNIT_INVENTIVE]
    assert Flag.NEEDS_HUMAN_REVIEW in part.flags


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
    # 겹침은 로그만이 아니라 결과에도 남는다: 남긴 묶음·버린 묶음
    assert [(o.claim, o.kept_unit, o.dropped_unit) for o in part.overlaps] == [
        (2, UNIT_INVENTIVE, UNIT_CLARITY)
    ]


def _three_units_data() -> dict:
    """명확성 묶음을 하나 더 복제해 묶음 셋(order 1·2·3)이 되게 한 사건."""
    data = json.loads((FIXTURES / "case_basic.json").read_text("utf-8"))
    data["spec"] = json.loads((FIXTURES / "spec_basic.pages.json").read_text("utf-8"))
    third = copy.deepcopy(data["units"][1])
    third.update(
        unit_id="oa_1:42-4-3:c3", order=3, representative_claim=3, claims=[3], read_with=[1, 2]
    )  # 청구항 1·2는 읽기만 하는 묶음
    data["units"].append(third)
    return data


def test_세_묶음이_같은_청구항을_겹쳐_고치면_버린_묶음마다_한_줄씩_남는다():
    first = copy.deepcopy(_answer("amendment_inventive"))
    first["claims"].append(copy.deepcopy(_answer("amendment_clarity")["claims"][0]))  # 청구항 1·2
    clarity = _answer("amendment_clarity")
    clarity_both = copy.deepcopy(clarity)
    clarity_both["claims"].insert(0, copy.deepcopy(_answer("amendment_inventive")["claims"][0]))
    inp = F4Input.model_validate(_three_units_data())
    part, _, _ = _run(
        [first, clarity_both, clarity_both],
        directions=("direction_inventive", "direction_clarity", "direction_clarity"),
        opinions=("opinion_inventive", "opinion_clarity", "opinion_clarity"),
        inp=inp,
    )
    third = "oa_1:42-4-3:c3"
    # (청구항, 남긴 묶음, 버린 묶음): 남긴 묶음은 늘 order 1, 버린 묶음마다 청구항 수만큼 한 줄
    assert sorted((o.claim, o.kept_unit, o.dropped_unit) for o in part.overlaps) == [
        (1, UNIT_INVENTIVE, UNIT_CLARITY),
        (1, UNIT_INVENTIVE, third),
        (2, UNIT_INVENTIVE, UNIT_CLARITY),
        (2, UNIT_INVENTIVE, third),
    ]


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
