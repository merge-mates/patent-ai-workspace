"""run_f4 한 바퀴와 누락 검사 테스트: 가짜 사건(fixture) + 가짜 전송층. 진짜 모델 호출 없음.

기대값은 구현 계획 C4, `docs/features/F4/design.md`
2절·3-2절(F4Output·사건 전체 검사), product.md 5절 F4 5·7번에서 가져왔다.
"""

import copy
import json
import logging
from pathlib import Path

import pytest

from patent_ai.core.f4_response_draft.coverage import unchecked_rejections, uncovered
from patent_ai.core.f4_response_draft.inputs import F4Input
from patent_ai.core.f4_response_draft.result import F4Output
from patent_ai.core.f4_response_draft.run import ALL_F4_CHECKED, run_f4
from patent_ai.core.llm.errors import ModelOutputInvalid
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.common import Flag, StatusValue
from patent_ai.core.schemas.oa_result import OAResult, build_rejection
from tests.core.f4.legal_fixture import confirmed_legal

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "f4"
UNIT_INVENTIVE = "oa_1:29-2:c1"
UNIT_CLARITY = "oa_1:42-4-2:c2"
OK = {"value": "confirmed", "checked": "원문 대조"}


def _case_data() -> dict:
    data = json.loads((FIXTURES / "case_basic.json").read_text("utf-8"))
    data["spec"] = json.loads((FIXTURES / "spec_basic.pages.json").read_text("utf-8"))
    return data


def _clean_case() -> dict:
    """앞 단계가 모두 확인됨인 사건: 안쪽에서 올라오는 직접 검토 표시가 없다."""
    data = _case_data()
    data["legal"] = [confirmed_legal(UNIT_INVENTIVE, 1), confirmed_legal(UNIT_CLARITY, 2)]
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


def test_결과에_판단_단위와_알림_문구가_실린다():
    data = _case_data()
    out, _ = _run(data)
    assert [u.unit_id for u in out.units] == [UNIT_INVENTIVE, UNIT_CLARITY]
    assert [u.model_dump(mode="json") for u in out.units] == data["units"]
    assert out.rank_notice == "순위는 검토 순서 제안이고 등록 가능성을 보증하지 않는다"
    assert "적법성" in out.legality_notice and "판단하지 않" in out.legality_notice


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
    assert out.status.checked == "방향 후보와 초안 모두 확인됨"
    assert out.flags == []
    assert out.coverage_unchecked == []


def test_앞_단계가_확인됨이어도_보류한_묶음이_있으면_확인_내용에_드러난다():
    out, _ = _run(
        _clean_case(),
        directions=("direction_inventive", "direction_low"),
        opinions=("opinion_inventive",),
        amendments=("amendment_inventive",),
    )
    # status 값은 원문 확인 여부라 그대로 확인됨. 사람 판단이 남았다는 것은 글·flags·held_units로
    assert out.status.value == StatusValue.CONFIRMED
    assert out.status.checked != "방향 후보와 초안 모두 확인됨"
    assert "보류 1묶음" in out.status.checked
    assert out.held_units == [UNIT_CLARITY]
    assert Flag.NEEDS_HUMAN_JUDGMENT in out.flags


def test_앞_단계가_확인됨이어도_누락_쌍이_있으면_확인_내용에_드러난다():
    data = _clean_case()
    data["units"][0]["claims"] = [1]
    out, _ = _run(data)
    assert out.status.value == StatusValue.CONFIRMED
    assert "누락 쌍 1" in out.status.checked and "모두 확인됨" not in out.status.checked
    assert out.uncovered == [(1, 2)]
    assert out.flags == [Flag.NEEDS_HUMAN_REVIEW]


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


# ---- 같은 청구항을 여러 묶음이 고침 ----
def test_뒤_묶음_초안을_싣지_않은_겹침이_결과와_확인_글에_드러난다():
    both = copy.deepcopy(_answer("amendment_inventive"))
    extra = copy.deepcopy(_answer("amendment_clarity")["claims"][0])
    both["claims"].append(extra)  # 진보성 묶음(order 1)이 청구항 2도 고침
    out, _ = _run(_clean_case(), amendments=(both, "amendment_clarity"))
    assert [(o.claim, o.kept_unit, o.dropped_unit) for o in out.amendment_overlaps] == [
        (2, UNIT_INVENTIVE, UNIT_CLARITY)
    ]
    assert out.status.checked != ALL_F4_CHECKED
    assert "같은 청구항을 여러 묶음이 고쳐 뒤 묶음 초안 1개를 싣지 않음" in out.status.checked
    assert "청구항 2" in out.status.checked and "직접 합치기 필요" in out.status.checked


def test_세_묶음이_겹쳐_고치면_확인_글의_개수는_초안_수고_청구항은_중복_없이_나온다():
    first = copy.deepcopy(_answer("amendment_inventive"))
    first["claims"].append(copy.deepcopy(_answer("amendment_clarity")["claims"][0]))  # 청구항 1·2
    clarity_both = copy.deepcopy(_answer("amendment_clarity"))
    clarity_both["claims"].insert(0, copy.deepcopy(_answer("amendment_inventive")["claims"][0]))
    third = "oa_1:42-4-3:c3"
    data = _clean_case()
    unit3 = copy.deepcopy(data["units"][1])
    unit3.update(unit_id=third, order=3, representative_claim=3, claims=[3], read_with=[1, 2])
    data["units"].append(unit3)
    data["legal"].append(confirmed_legal(third, 2))
    clarity3 = copy.deepcopy(data["clarity"][0])  # 셋째 묶음도 F3 명확성 결과가 있어야 확인됨
    clarity3.update(unit_id=third, claim=3)
    data["clarity"].append(clarity3)
    out, _ = _run(
        data,
        directions=("direction_inventive", "direction_clarity", "direction_clarity"),
        opinions=("opinion_inventive", "opinion_clarity", "opinion_clarity"),
        amendments=(first, clarity_both, clarity_both),
    )
    assert len(out.amendment_overlaps) == 4
    # 버린 초안은 4개, 겹친 청구항은 1·2 두 개 (개수는 초안 수, 번호는 중복 없이)
    assert "뒤 묶음 초안 4개를 싣지 않음(청구항 1, 2, 직접 합치기 필요)" in out.status.checked


def test_겹침이_없으면_겹침_목록이_비어_있다():
    out, _ = _run(_clean_case())
    assert out.amendment_overlaps == []


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
    assert out.status.value == plain.status.value  # 값은 달라지지 않음 (글만 달라진다)
    assert out.uncovered == []  # 지원 안 하는 거절이유의 청구항은 누락으로 세지 않는다
    # status 값은 같아도 확인 글은 "모두 확인됨"이 아니고, 다루지 않은 거절이유가 글로 드러난다
    assert plain.status.checked == ALL_F4_CHECKED
    assert out.status.checked != ALL_F4_CHECKED
    assert "AI가 다루지 않은 거절이유 1개(직접 대응 필요)" in out.status.checked


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
