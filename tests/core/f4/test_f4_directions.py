"""F4 방향 후보 단계 테스트: 지어낸 가짜 사건(fixture) + 가짜 전송층(사람이 쓴 답).

진짜 모델 호출 없음.

기대값은 구현 계획 C1, `docs/features/F4/design.md`
2절 ①·3-1절(빈 법률 근거)·3-2절 ⑤·4절(보정 제한), 스키마 검사(direction.py),
product.md 5절 F4에서 가져왔다.
"""

import copy
import json
import logging
from pathlib import Path

import pytest

from patent_ai.core.f4_response_draft.config import F4Options
from patent_ai.core.f4_response_draft.directions import (
    RANK_NOTICE,
    STEP,
    amendment_limit_of,
    build_directions,
)
from patent_ai.core.f4_response_draft.inputs import F4Input
from patent_ai.core.llm.errors import ModelCallLimitExceeded, ModelOutputInvalid
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.common import Flag, Origin, StatusValue, UnverifiedReason
from patent_ai.core.schemas.direction import AmendmentLimit, Confidence

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "f4"
UNIT_INVENTIVE = "oa_1:29-2:c1"
UNIT_CLARITY = "oa_1:42-4-2:c2"


def _case_data() -> dict:
    return json.loads((FIXTURES / "case_basic.json").read_text("utf-8"))


def _case(data: dict | None = None) -> F4Input:
    return F4Input.model_validate(data or _case_data())


def _answer(name: str) -> dict:
    return json.loads((FIXTURES / "llm" / f"{name}.json").read_text("utf-8"))


def _text(answer: dict) -> TransportResponse:
    return TransportResponse(json.dumps(answer, ensure_ascii=False), 100, 50)


def _run(responses: list, inp: F4Input | None = None, options: F4Options | None = None):
    """방향 후보 단계를 가짜 전송층으로 돌린다. responses는 부르는 순서대로의 답."""
    transport = FakeTransport({STEP: responses})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    return build_directions(inp or _case(), ctx, options=options), transport


def _basic():
    return _run([_text(_answer("direction_inventive")), _text(_answer("direction_clarity"))])


def _with_notice_kind(value: str) -> F4Input:
    """통지 종류만 바꾼 가짜 사건. unknown은 못 읽은 것이라 OA 전체도 확인되지 않음이 된다."""
    data = _case_data()
    if value == "unknown":
        bad = {"value": "unverified", "reason": "not_extracted"}
        data["oa"]["notice_kind"] = {"value": "unknown", "status": bad}
        data["oa"]["status"] = bad
    else:
        data["oa"]["notice_kind"] = {
            "value": value,
            "raw_text": "최후거절이유통지",
            "page": 1,
            "status": {"value": "confirmed", "checked": "원문 대조"},
        }
    return _case(data)


# ---- 모든 판단 단위에 하나씩 ----
def test_판단_단위마다_방향_후보_결과가_하나씩_나오고_모델은_단위마다_한_번():
    results, transport = _basic()
    assert [r.unit_id for r in results] == [UNIT_INVENTIVE, UNIT_CLARITY]  # order 순
    assert [c["step"] for c in transport.calls] == ["f4.direction", "f4.direction"]
    assert [len(r.candidates) for r in results] == [2, 1]
    for r in results:
        ids = [c.candidate_id for c in r.candidates]
        assert len(set(ids)) == len(ids)


def test_모델이_후보를_0개_주면_확인되지_않음과_직접_판단_필요(caplog):
    with caplog.at_level(logging.WARNING):
        results, _ = _run([_text({"candidates": []}), _text(_answer("direction_clarity"))])
    empty = results[0]
    assert empty.unit_id == UNIT_INVENTIVE and empty.candidates == []
    assert empty.status.value == StatusValue.UNVERIFIED
    assert Flag.NEEDS_HUMAN_JUDGMENT in empty.flags
    assert empty.selection is None
    assert "후보" in caplog.text  # 빈 목록은 경고를 남긴다


def test_판단_단위가_없으면_모델을_안_부르고_경고(caplog):
    data = _case_data()
    data["units"] = []
    with caplog.at_level(logging.WARNING):
        results, transport = _run([], _case(data))
    assert results == [] and transport.calls == []
    assert "판단 단위" in caplog.text


def test_판단_단위가_상한보다_많으면_모델을_부르기_전에_멈춘다():
    options = F4Options(final_rejection_limit=False, max_units=1, max_candidates=3)
    transport = FakeTransport({STEP: []})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    with pytest.raises(ModelCallLimitExceeded):
        build_directions(_case(), ctx, options=options)
    assert transport.calls == []


# ---- AI 기본값 / 사람 선택 구분 ----
def test_1등_후보가_AI_기본값으로_미리_선택된다():
    results, _ = _basic()
    for r in results:
        chosen = next(c for c in r.candidates if c.candidate_id == r.selection.candidate_id)
        assert chosen.rank == 1
        assert r.selection.origin == Origin.AI_DEFAULT
        # 맨 위 origin은 AI 생성 그대로 (사람 선택은 selection.origin 한 곳)
        assert r.origin == Origin.AI_GENERATED


# ---- 확신 낮음 ----
def test_확신이_낮으면_순위_없이_직접_판단_필요이고_미리_고르지_않는다():
    results, _ = _run([_text(_answer("direction_inventive")), _text(_answer("direction_low"))])
    low = results[1]
    assert len(low.candidates) == 2
    for c in low.candidates:
        assert c.confidence == Confidence.LOW and c.rank is None
        assert Flag.NEEDS_HUMAN_JUDGMENT in c.flags
    assert low.selection is None
    assert Flag.NEEDS_HUMAN_JUDGMENT in low.flags
    # 다른 묶음은 그대로 1등이 선택됨
    assert results[0].selection.origin == Origin.AI_DEFAULT


# ---- 모델이 낸 순서는 그대로 남는다 (채점이 "모델의 1번 후보"를 읽는다) ----
def test_확신_낮음뿐인_묶음도_모델이_낸_순서가_결과에_남는다():
    answer = _answer("direction_low")
    results, _ = _run([_text(_answer("direction_inventive")), _text(answer)])
    low = results[1]
    assert [c.name for c in low.candidates] == [c["name"] for c in answer["candidates"]]
    assert [c.candidate_id for c in low.candidates] == [f"{UNIT_CLARITY}:d1", f"{UNIT_CLARITY}:d2"]
    # 순서는 남지만 화면에 보일 순위는 여전히 없다: 미리 고르지 않고 직접 판단 필요
    assert all(c.rank is None for c in low.candidates)
    assert low.selection is None and Flag.NEEDS_HUMAN_JUDGMENT in low.flags


def test_순위_있는_후보와_낮은_후보가_섞여_와도_모델이_낸_순서_그대로다():
    answer = copy.deepcopy(_answer("direction_inventive"))
    first_low = copy.deepcopy(
        answer["candidates"][1]
    )  # 보정 없이 반박 후보를 확신 낮음으로 맨 앞에
    first_low.update(rank=None, confidence="low", name="확신 낮은 첫 후보")
    answer["candidates"][1]["rank"] = 2
    answer["candidates"] = [first_low, answer["candidates"][0], answer["candidates"][1]]
    results, _ = _run([_text(answer), _text(_answer("direction_clarity"))])
    mixed = results[0]
    assert [c.name for c in mixed.candidates] == [c["name"] for c in answer["candidates"]]
    assert [c.rank for c in mixed.candidates] == [None, 1, 2]
    assert [c.candidate_id for c in mixed.candidates] == [
        f"{UNIT_INVENTIVE}:d{n}" for n in (1, 2, 3)
    ]
    # AI 기본값은 여전히 순위 1 후보 (목록의 첫째가 아니라)
    assert mixed.selection.candidate_id == f"{UNIT_INVENTIVE}:d2"
    assert mixed.selection.origin == Origin.AI_DEFAULT


def _low_with_rank() -> dict:
    bad = copy.deepcopy(_answer("direction_low"))
    bad["candidates"][0]["rank"] = 1  # 낮은 확신에 순위를 붙임 (규칙 위반)
    return bad


def test_낮은_확신에_순위를_붙여_오면_한_번_다시_부른다():
    results, transport = _run(
        [
            _text(_answer("direction_inventive")),
            _text(_low_with_rank()),
            _text(_answer("direction_low")),
        ]
    )
    assert len(transport.calls) == 3  # 첫 묶음 1번 + 둘째 묶음 2번
    assert all(c.rank is None for c in results[1].candidates)
    assert results[1].selection is None


def test_다시_불러도_틀리면_실패가_그대로_드러난다():
    transport = FakeTransport({STEP: [_text(_low_with_rank()), _text(_low_with_rank())]})
    recorder = MemoryRecorder()
    ctx = RunContext(run_id="r_1", budget=CallBudget(), recorder=recorder, transport=transport)
    data = _case_data()
    data["units"] = data["units"][1:]  # 명확성 묶음 하나만
    data["tables"] = []
    with pytest.raises(ModelOutputInvalid):
        build_directions(_case(data), ctx)
    assert len(transport.calls) == 2  # 첫 호출 + 다시 한 번, 그 뒤로는 안 부름
    assert [r.outcome for r in recorder.records] == ["invalid_output", "invalid_output"]


def test_답이_JSON이_아니어도_한_번만_다시_부른다():
    garbage = TransportResponse("방향 후보는 다음과 같습니다", 100, 50)
    transport = FakeTransport({STEP: [garbage, garbage]})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    with pytest.raises(ModelOutputInvalid):
        build_directions(_case(), ctx)
    assert len(transport.calls) == 2


# ---- 그 밖의 출력 검사 (스키마 규칙·설정 상한) ----
def test_후보가_설정_상한보다_많으면_출력_검사_실패():
    options = F4Options(final_rejection_limit=False, max_units=20, max_candidates=1)
    two = _text(_answer("direction_inventive"))  # 후보 2개
    transport = FakeTransport({STEP: [two, two]})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    with pytest.raises(ModelOutputInvalid):
        build_directions(_case(), ctx, options=options)
    assert len(transport.calls) == 2  # 첫 호출 + 다시 한 번


def test_거절이유_종류에_안_맞는_반박_유형은_출력_검사_실패_뒤_다시_부른다():
    bad = copy.deepcopy(_answer("direction_inventive"))
    bad["candidates"][0]["rebuttal"]["type"] = "obvious_error"  # 명확성용 유형을 진보성에
    results, transport = _run(
        [_text(bad), _text(_answer("direction_inventive")), _text(_answer("direction_clarity"))]
    )
    assert len(transport.calls) == 3
    assert results[0].candidates[0].rebuttal.rejection_kind == "inventive_step"


def test_OA에_없는_거절이유_번호는_틀린_번호만_오류에_찍힌다():
    bad = copy.deepcopy(_answer("direction_inventive"))
    bad["candidates"][0]["per_rejection"].append({"rejection": 9, "response": "없는 번호"})
    transport = FakeTransport({STEP: [_text(bad), _text(bad)]})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    with pytest.raises(ModelOutputInvalid, match=r"OA에 없는 거절이유 번호: \[9\]"):
        build_directions(_case(), ctx)


def test_묶음_밖_청구항을_보정하겠다는_후보는_출력_검사_실패():
    bad = copy.deepcopy(_answer("direction_clarity"))
    bad["candidates"][0]["amendment_core"] = [{"claim": 9, "kind": "clarify"}]
    transport = FakeTransport(
        {STEP: [_text(_answer("direction_inventive")), _text(bad), _text(bad)]}
    )
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    with pytest.raises(ModelOutputInvalid):
        build_directions(_case(), ctx)


# ---- 순위는 보증이 아니라는 문구 (결과에 싣는 것은 run_f4, test_f4_run.py) ----
def test_순위는_보증이_아니라는_문구가_상수로_있다():
    assert RANK_NOTICE == "순위는 검토 순서 제안이고 등록 가능성을 보증하지 않는다"


# ---- status 전파와 근거 ----
def test_후보_status는_F3_결과와_빈_법률_근거를_전파한_확인되지_않음():
    results, _ = _basic()
    for r in results:
        for c in r.candidates:
            assert c.status.value == StatusValue.UNVERIFIED
            assert c.status.reason == UnverifiedReason.INPUT_UNVERIFIED
        assert r.status.value == StatusValue.UNVERIFIED


def test_F3_결과가_없는_묶음도_확인되지_않음이고_근거가_비어_있다(caplog):
    data = _case_data()
    data["tables"] = []
    with caplog.at_level(logging.WARNING):
        results, _ = _run(
            [_text(_answer("direction_inventive")), _text(_answer("direction_clarity"))],
            _case(data),
        )
    first = results[0].candidates[0]
    assert first.status.reason == UnverifiedReason.INPUT_UNVERIFIED
    assert first.evidence == []
    assert UNIT_INVENTIVE in caplog.text


def test_후보_근거는_F3_결과의_근거만_담는다():
    inp = _case()
    results, _ = _basic()
    table = inp.tables[0]
    expected = [e for row in table.rows for e in row.evidence]
    for c in results[0].candidates:
        assert c.evidence == expected  # 대비표 줄의 근거 (같은 근거는 한 번)
    # 명확성 결과의 근거는 spec_definition(명세서 정의 위치) 한 곳이다
    assert inp.clarity[0].spec_definition is not None
    assert results[1].candidates[0].evidence == [inp.clarity[0].spec_definition]


def test_모델이_근거를_지어내_붙이면_받지_않는다():
    invented = copy.deepcopy(_answer("direction_clarity"))
    invented["candidates"][0]["evidence"] = [
        {"document_id": "지어낸_문헌", "page": 1, "raw_text": "지어낸 문장"}
    ]
    results, transport = _run(
        [
            _text(_answer("direction_inventive")),
            _text(invented),
            _text(_answer("direction_clarity")),
        ]
    )
    assert len(transport.calls) == 3  # 근거 칸이 있는 답은 출력 검사에 떨어져 다시 부름
    docs = {e.document_id for r in results for c in r.candidates for e in c.evidence}
    assert "지어낸_문헌" not in docs


# ---- 보정 제한: OA 통지 종류 사실 그대로 ----
def test_최초_통지면_보정_제한은_initial():
    results, _ = _basic()
    for r in results:
        assert r.amendment_limit.value == AmendmentLimit.INITIAL
        assert r.amendment_limit.status.value == StatusValue.CONFIRMED


def test_최후_통지면_보정_제한은_final이고_원문_글자가_따라온다():
    inp = _with_notice_kind("final")
    results, _ = _run(
        [_text(_answer("direction_inventive")), _text(_answer("direction_clarity"))], inp
    )
    limit = results[0].amendment_limit
    assert limit.value == AmendmentLimit.FINAL
    assert (limit.raw_text, limit.page) == ("최후거절이유통지", 1)
    assert limit.status.value == StatusValue.CONFIRMED


def test_통지_종류를_모르면_보정_제한은_값_없이_확인되지_않음():
    inp = _with_notice_kind("unknown")
    limit = amendment_limit_of(inp.oa)
    assert limit.value is None
    assert limit.status.value == StatusValue.UNVERIFIED
    assert limit.status.reason == UnverifiedReason.NOT_EXTRACTED  # 원래 이유 그대로
    results, _ = _run(
        [_text(_answer("direction_inventive")), _text(_answer("direction_clarity"))], inp
    )
    assert all(r.amendment_limit == limit for r in results)
    assert all(r.status.value == StatusValue.UNVERIFIED for r in results)


# ---- 청구항 글자가 입력에 없음 ----
def test_청구항_글자가_입력에_없으면_결과에_직접_검토_필요를_붙인다(caplog):
    data = _case_data()
    data["claims_text"] = [c for c in data["claims_text"] if c["claim"] != 2]
    with caplog.at_level(logging.WARNING):
        results, _ = _run(
            [_text(_answer("direction_inventive")), _text(_answer("direction_clarity"))],
            _case(data),
        )
    # 두 묶음 모두 청구항 2를 쓴다 (진보성 묶음의 종속항, 명확성 묶음의 대표 청구항)
    assert all(Flag.NEEDS_HUMAN_REVIEW in r.flags for r in results)
    assert "청구항 글자" in caplog.text


def test_청구항_글자가_다_있으면_직접_검토_필요를_붙이지_않는다():
    results, _ = _basic()
    assert all(Flag.NEEDS_HUMAN_REVIEW not in r.flags for r in results)
