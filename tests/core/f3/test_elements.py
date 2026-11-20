"""구성요소 나누기(B1) 테스트: 손으로 지어낸 청구항 + 가짜 전송층(기록된 모델 응답). 진짜 호출 없음.

기대값은 구현 계획(B1)과 F3 뼈대 설계 4절에서 가져왔다. 프롬프트 문구는 테스트하지 않는다.
"""

import json
import logging

import pytest

from patent_ai.core.f3_claim_compare.elements import STEP, split_elements
from patent_ai.core.llm.errors import ModelOutputInvalid
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.common import StatusValue, UnverifiedReason

# 지어낸 청구항 (진짜 사건 글자 아님). 청구항 2는 줄바꿈·겹친 공백이 섞여 있다
CLAIM_1 = (
    "화분에 있어서,\n"
    "흙의 습도를 재는 습도 센서;\n"
    "물을 담는 물통; 및\n"
    "상기 습도 센서의 값이 기준보다 낮으면 상기 물통의 물을 내보내는 제어부를 포함하는 화분."
)
CLAIM_2 = "제1항에 있어서,\n상기 물통은 투명한\n  재질로 이루어진 화분."
CLAIMS = {
    1: CLAIM_1,
    2: CLAIM_2,
    3: "제1항 또는 제2항에 있어서, 상기 화분은 받침을 더 포함하는 화분.",
}

SENSOR = "흙의 습도를 재는 습도 센서"
TANK = "물을 담는 물통"
CONTROL = "상기 습도 센서의 값이 기준보다 낮으면 상기 물통의 물을 내보내는 제어부"


def _answer(claim: int, elements: list[str], depends_on=(), quote=None) -> TransportResponse:
    """기록된 모델 응답 하나 (ClaimElements 모양 JSON)."""
    body = {
        "claim": claim,
        "depends_on": list(depends_on),
        "depends_on_quote": quote,
        "elements": [{"text": t} for t in elements],
    }
    return TransportResponse(json.dumps(body, ensure_ascii=False), 100, 50)


GOOD_1 = _answer(1, [SENSOR, TANK, CONTROL])
GOOD_2 = _answer(2, ["상기 물통은 투명한 재질로 이루어진"], [1], "제1항에 있어서")


def _split(claim: int, responses, claims: dict[int, str] | None = None):
    """split_elements를 가짜 전송층으로 돌린다. responses: 답 하나 또는 차례로 낼 목록."""
    claims = claims or CLAIMS
    transport = FakeTransport({STEP: responses})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    result = split_elements(claim, claims[claim], sorted(claims), ctx=ctx)
    return result, transport


def _is_unverified(status, reason: UnverifiedReason) -> bool:
    return status.value == StatusValue.UNVERIFIED and status.reason == reason


# ---- 같은 입력 → 같은 결과 ----
def test_같은_입력을_두_번_나누면_결과가_같다():
    first, _ = _split(1, GOOD_1)
    second, _ = _split(1, GOOD_1)
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


# ---- 원문 위치 ----
def test_구성요소마다_원문_위치가_있다():
    result, transport = _split(1, GOOD_1)
    assert len(transport.calls) == 1 and transport.calls[0]["step"] == STEP
    assert [e.text for e in result.elements] == [SENSOR, TANK, CONTROL]
    assert [e.no for e in result.elements] == [1, 2, 3]
    assert [e.element_location for e in result.elements] == [
        "청구항 1 [구성 1-1]",
        "청구항 1 [구성 1-2]",
        "청구항 1 [구성 1-3]",
    ]
    for e in result.elements:
        assert e.claim == 1
        assert CLAIM_1[e.start : e.end] == e.text  # 오프셋이 원문 그 글자를 가리킨다
        assert e.status.value == StatusValue.CONFIRMED
    # 겹치지 않고 원문 순서대로
    assert [e.start for e in result.elements] == sorted(e.start for e in result.elements)
    assert all(a.end <= b.start for a, b in zip(result.elements, result.elements[1:], strict=False))
    assert result.status.value == StatusValue.CONFIRMED
    assert result.claim == 1 and result.depends_on == []


def test_공백만_다른_구성요소는_원문_글자_그대로_찾는다():
    result, transport = _split(2, GOOD_2)
    assert len(transport.calls) == 1  # 공백 차이는 검사 오류가 아니다
    (e,) = result.elements
    assert e.status.value == StatusValue.CONFIRMED
    assert e.text == "상기 물통은 투명한\n  재질로 이루어진"  # 원문 글자 그대로
    assert CLAIM_2[e.start : e.end] == e.text
    assert e.element_location == "청구항 2 [구성 2-1]"


def test_프롬프트에_청구항_글자가_들어간다():
    _, transport = _split(1, GOOD_1)
    assert SENSOR in transport.calls[0]["prompt"]


# ---- 원문에 없는 구성요소 글자 ----
def test_원문에_없는_구성요소는_한_번_다시_불러_고쳐_오면_통과한다():
    bad = _answer(1, [SENSOR, "물을 저장하는 탱크", CONTROL])
    result, transport = _split(1, [bad, GOOD_1])
    assert len(transport.calls) == 2
    assert "검사 오류" in transport.calls[1]["prompt"]  # 검사 오류를 붙여 다시 부른다
    assert "검사 오류" not in transport.calls[0]["prompt"]
    assert [e.status.value for e in result.elements] == [StatusValue.CONFIRMED] * 3
    assert result.status.value == StatusValue.CONFIRMED


def test_다시_불러도_원문에_없으면_그_구성요소만_확인되지_않음(caplog):
    bad = _answer(1, [SENSOR, "물을 저장하는 탱크", CONTROL])
    with caplog.at_level(logging.WARNING):
        result, transport = _split(1, [bad, bad])
    assert len(transport.calls) == 2  # 다시 부르는 것은 한 번뿐
    first, second, third = result.elements  # 조용히 버리지 않는다
    assert first.status.value == third.status.value == StatusValue.CONFIRMED
    assert _is_unverified(second.status, UnverifiedReason.NOT_EXTRACTED)
    assert (second.start, second.end) == (None, None)
    assert second.element_location == "청구항 1 [구성 1-2]"
    assert CLAIM_1[third.start : third.end] == CONTROL  # 뒤 구성요소는 그대로 찾는다
    assert _is_unverified(result.status, UnverifiedReason.NOT_EXTRACTED)
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_원문_순서와_다르게_준_구성요소는_확인되지_않음():
    # 물통이 센서보다 앞에 왔다: 앞 구성요소 끝 뒤에서만 찾으므로 센서를 못 찾는다
    swapped = _answer(1, [TANK, SENSOR, CONTROL])
    result, transport = _split(1, [swapped, swapped])
    assert len(transport.calls) == 2
    tank, sensor, control = result.elements
    assert tank.status.value == control.status.value == StatusValue.CONFIRMED
    assert _is_unverified(sensor.status, UnverifiedReason.NOT_EXTRACTED)


def test_빈_구성요소_글자는_확인되지_않음():
    blank = _answer(1, [SENSOR, "   "])
    result, _ = _split(1, [blank, blank])
    assert _is_unverified(result.elements[1].status, UnverifiedReason.NOT_EXTRACTED)


# ---- 인용 관계 (depends_on) ----
def test_종속항은_인용구가_원문에_있고_번호가_맞으면_확인됨():
    result, _ = _split(2, GOOD_2)
    assert result.depends_on == [1]
    assert result.depends_on_quote == "제1항에 있어서"
    assert result.depends_on_status.value == StatusValue.CONFIRMED
    assert result.status.value == StatusValue.CONFIRMED


def test_인용구가_원문에_없으면_한_번_다시_불러_고쳐_오면_통과한다():
    bad = _answer(2, ["상기 물통은 투명한 재질로 이루어진"], [1], "청구항 1에 따른")
    result, transport = _split(2, [bad, GOOD_2])
    assert len(transport.calls) == 2
    assert "검사 오류" in transport.calls[1]["prompt"]
    assert result.depends_on == [1]
    assert result.depends_on_status.value == StatusValue.CONFIRMED


@pytest.mark.parametrize(
    ("depends_on", "quote"),
    [
        ([1], "청구항 1에 따른"),  # 인용구가 원문에 없음
        ([7], "제1항에 있어서"),  # 그 사건 청구항 번호가 아님
        ([2], "제1항에 있어서"),  # 자기 자신
        ([3], "제1항에 있어서"),  # 자기보다 큰 번호
        ([1], None),  # 번호는 있는데 인용구가 없음
        ([], "제1항에 있어서"),  # 인용구는 있는데 번호가 없음
    ],
)
def test_다시_불러도_인용이_틀리면_인용_관계는_확인되지_않음(depends_on, quote, caplog):
    bad = _answer(2, ["상기 물통은 투명한 재질로 이루어진"], depends_on, quote)
    with caplog.at_level(logging.WARNING):
        result, transport = _split(2, [bad, bad])
    assert len(transport.calls) == 2
    assert result.depends_on is None and result.depends_on_quote is None  # 틀린 값을 싣지 않는다
    assert _is_unverified(result.depends_on_status, UnverifiedReason.NOT_EXTRACTED)
    # 구성요소는 인용 관계와 따로 확인한다
    assert result.elements[0].status.value == StatusValue.CONFIRMED
    assert _is_unverified(result.status, UnverifiedReason.NOT_EXTRACTED)
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_여러_항을_인용하는_종속항():
    answer = _answer(3, ["상기 화분은 받침을 더 포함하는"], [1, 2], "제1항 또는 제2항에 있어서")
    result, _ = _split(3, answer)
    assert result.depends_on == [1, 2]
    assert result.depends_on_status.value == StatusValue.CONFIRMED


# ---- 구성요소 0개 ----
def test_구성요소가_0개면_경고하고_성공으로_숨기지_않는다(caplog):
    empty = _answer(1, [])
    with caplog.at_level(logging.WARNING):
        result, transport = _split(1, [empty, empty])
    assert len(transport.calls) == 2  # 0개도 검사 오류라 한 번 다시 부른다
    assert result.elements == []
    assert _is_unverified(result.status, UnverifiedReason.NOT_EXTRACTED)
    assert any("0개" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


def test_구성요소_0개였다가_다시_불러_고쳐_오면_통과한다():
    result, transport = _split(1, [_answer(1, []), GOOD_1])
    assert len(transport.calls) == 2
    assert len(result.elements) == 3 and result.status.value == StatusValue.CONFIRMED


# ---- 출력 형식 검사 실패 (F1과 같은 길) ----
def test_답이_JSON이_아니면_한_번_다시_부른다():
    broken = TransportResponse("구성요소는 다음과 같습니다", 100, 50)
    result, transport = _split(1, [broken, GOOD_1])
    assert len(transport.calls) == 2
    assert result.status.value == StatusValue.CONFIRMED


def test_두_번_다_형식이_틀리면_예외로_끝난다():
    broken = TransportResponse("구성요소는 다음과 같습니다", 100, 50)
    with pytest.raises(ModelOutputInvalid):
        _split(1, [broken, broken])


def test_다른_청구항_번호로_답하면_검사_오류로_다시_부른다():
    wrong_claim = _answer(2, [SENSOR, TANK, CONTROL])
    result, transport = _split(1, [wrong_claim, GOOD_1])
    assert len(transport.calls) == 2
    assert result.claim == 1 and result.status.value == StatusValue.CONFIRMED


# ---- 청구항 글자가 비어 있음 ----
def test_청구항_글자가_비면_모델을_부르지_않고_확인되지_않음(caplog):
    with caplog.at_level(logging.WARNING):
        result, transport = _split(1, GOOD_1, claims={1: "  \n", 2: CLAIM_2})
    assert transport.calls == []
    assert result.elements == []
    assert _is_unverified(result.status, UnverifiedReason.INPUT_UNVERIFIED)
    assert any(r.levelno == logging.WARNING for r in caplog.records)
