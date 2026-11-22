"""구성요소 나누기(B1) 테스트: 손으로 지어낸 청구항 + 가짜 전송층(가짜 응답). 진짜 호출 없음.

기대값은 구현 계획(B1)과 F3 뼈대 설계 4절에서 가져왔다. 프롬프트 문구는 테스트하지 않는다.
"""

import json
import logging

import pytest

from patent_ai.core.f3_claim_compare.elements import STEP, split_elements
from patent_ai.core.llm.cache import MemoryCache
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
    """가짜 응답 하나 (ClaimElements 모양 JSON)."""
    body = {
        "claim": claim,
        "depends_on": list(depends_on),
        "depends_on_quote": quote,
        "elements": [{"text": t} for t in elements],
    }
    return TransportResponse(json.dumps(body, ensure_ascii=False), 100, 50)


GOOD_1 = _answer(1, [SENSOR, TANK, CONTROL])
GOOD_2 = _answer(2, ["상기 물통은 투명한 재질로 이루어진"], [1], "제1항에 있어서")


def _split(claim: int, responses, claims: dict[int, str] | None = None, ctx=None):
    """split_elements를 가짜 전송층으로 돌린다. responses: 답 하나 또는 차례로 낼 목록.

    ctx를 넘기면 그 ctx로 부른다 (같은 ctx로 여러 번 부를 때). 그 ctx의 transport를 돌려준다.
    """
    claims = claims or CLAIMS
    if ctx is None:
        transport = FakeTransport({STEP: responses})
        ctx = RunContext(
            run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
        )
    transport = ctx.transport
    result = split_elements(claim, claims[claim], sorted(claims), ctx=ctx)
    return result, transport


def _split_warnings(caplog) -> list[str]:
    """구성요소 나누기 모듈이 낸 경고만 (llm.config의 price 경고는 매번 나와서 거른다)."""
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.WARNING and r.name == "patent_ai.core.f3_claim_compare.elements"
    ]


def _is_unverified(status, reason: UnverifiedReason) -> bool:
    return status.value == StatusValue.UNVERIFIED and status.reason == reason


# ---- 같은 입력 → 같은 결과 ----
def test_같은_입력을_두_번_나누면_모델은_한_번만_불리고_결과가_같다():
    # 같은 ctx(같은 메모리 캐시)로 두 번 부른다: 두 번째는 캐시에서 나와 전송이 일어나지 않는다
    transport = FakeTransport({STEP: GOOD_1})
    ctx = RunContext(
        run_id="r_1",
        budget=CallBudget(),
        recorder=MemoryRecorder(),
        transport=transport,
        cache=MemoryCache(),
    )
    first, _ = _split(1, GOOD_1, ctx=ctx)
    second, _ = _split(1, GOOD_1, ctx=ctx)
    assert len(transport.calls) == 1
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
    assert _split_warnings(caplog)


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
    assert _split_warnings(caplog)


def test_여러_항을_인용하는_종속항():
    answer = _answer(3, ["상기 화분은 받침을 더 포함하는"], [1, 2], "제1항 또는 제2항에 있어서")
    result, _ = _split(3, answer)
    assert result.depends_on == [1, 2]
    assert result.depends_on_status.value == StatusValue.CONFIRMED


def test_인용구_안_번호와_depends_on이_다르면_인용_관계는_확인되지_않음(caplog):
    # 원문은 "제1항"인데 모델이 depends_on=[2]로 답했다 (인용구 글자는 원문에 있어 글자 대조는 통과)
    # (청구항 3의 원문을 "제1항에 있어서"로 시작하게 두고, 모델은 앞 번호 2를 인용했다고 답함)
    wrong = _answer(3, ["상기 물통은 투명한 재질로 이루어진"], [2], "제1항에 있어서")
    with caplog.at_level(logging.WARNING):
        result, transport = _split(3, [wrong, wrong], claims={**CLAIMS, 3: CLAIM_2})
    assert len(transport.calls) == 2  # 검사 오류로 한 번 다시 부르고, 또 틀리면 끝
    assert result.depends_on is None and result.depends_on_quote is None
    assert _is_unverified(result.depends_on_status, UnverifiedReason.NOT_EXTRACTED)
    assert result.status.value == StatusValue.UNVERIFIED
    assert _split_warnings(caplog)


def test_인용구_번호가_다르면_다시_불러_고쳐_오면_통과한다():
    wrong = _answer(3, ["상기 물통은 투명한 재질로 이루어진"], [2], "제1항에 있어서")
    good = _answer(3, ["상기 물통은 투명한 재질로 이루어진"], [1], "제1항에 있어서")
    result, transport = _split(3, [wrong, good], claims={**CLAIMS, 3: CLAIM_2})
    assert len(transport.calls) == 2
    assert "검사 오류" in transport.calls[1]["prompt"]
    assert result.depends_on == [1] and result.status.value == StatusValue.CONFIRMED


def test_원문이_제N항으로_시작하는데_독립항으로_답하면_확인되지_않음(caplog):
    # 인용 문구가 있는 종속항을 모델이 독립항으로 읽었다 (depends_on=[], 인용구 없음)
    as_independent = _answer(2, ["상기 물통은 투명한 재질로 이루어진"])
    with caplog.at_level(logging.WARNING):
        result, transport = _split(2, [as_independent, as_independent])
    assert len(transport.calls) == 2
    assert result.depends_on is None
    assert _is_unverified(result.depends_on_status, UnverifiedReason.NOT_EXTRACTED)
    assert result.status.value == StatusValue.UNVERIFIED
    assert _split_warnings(caplog)


def test_제N항_또는_제M항_인용은_번호가_같으면_확인됨():
    answer = _answer(3, ["상기 화분은 받침을 더 포함하는"], [2, 1], "제1항 또는 제2항에 있어서")
    result, transport = _split(3, answer)
    assert len(transport.calls) == 1
    assert result.depends_on == [1, 2] and result.status.value == StatusValue.CONFIRMED


def test_내지_범위_인용은_사이_번호까지_펼쳐_비교한다():
    claims = {1: "가.", 2: "나.", 3: "다.", 4: "제1항 내지 제3항 중 어느 한 항에 있어서, 라 화분."}
    quote = "제1항 내지 제3항 중 어느 한 항에 있어서"
    good = _answer(4, ["라 화분"], [1, 2, 3], quote)
    result, transport = _split(4, good, claims=claims)
    assert len(transport.calls) == 1 and result.depends_on == [1, 2, 3]
    short = _answer(4, ["라 화분"], [1, 3], quote)  # 가운데 2가 빠짐
    result, transport = _split(4, [short, short], claims=claims)
    assert len(transport.calls) == 2 and result.depends_on is None


def test_독립항_원문은_제N항_꼴이_없으므로_독립항_답이_확인됨_그대로다():
    result, transport = _split(1, GOOD_1)
    assert len(transport.calls) == 1 and result.depends_on == []
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
    assert _split_warnings(caplog)


# ---- 같은 문구가 원문에 여러 번 나올 때 (B1 리뷰) ----
REPEATED = "습도 센서를 구비한 화분에 있어서, 습도 센서; 및 물통을 포함하는 화분."


def test_같은_문구가_다음_구성요소_앞에_또_있으면_위치를_정하지_않고_애매로_둔다(caplog):
    # 전제부의 "습도 센서"와 본문의 "습도 센서" 중 어느 것인지 원문만으로는 가릴 수 없다
    answer = _answer(1, ["습도 센서", "물통"])
    with caplog.at_level(logging.WARNING):
        result, transport = _split(1, [answer, answer], claims={1: REPEATED})
    assert len(transport.calls) == 2  # 검사 오류로 한 번 다시 부른다
    sensor, tank = result.elements
    assert _is_unverified(sensor.status, UnverifiedReason.AMBIGUOUS)
    assert (sensor.start, sensor.end) == (None, None)  # 틀릴 수 있는 위치를 싣지 않는다
    assert tank.status.value == StatusValue.CONFIRMED
    assert REPEATED[tank.start : tank.end] == "물통"
    assert result.status.value == StatusValue.UNVERIFIED
    assert _split_warnings(caplog)


def test_앞뒤_글자를_더_넣어_하나로_정해지면_확인됨():
    vague = _answer(1, ["습도 센서", "물통"])
    exact = _answer(1, ["습도 센서;", "물통"])
    result, transport = _split(1, [vague, exact], claims={1: REPEATED})
    assert len(transport.calls) == 2
    sensor = result.elements[0]
    assert sensor.status.value == StatusValue.CONFIRMED
    assert (sensor.start, REPEATED[sensor.start : sensor.end]) == (20, "습도 센서;")


def test_종속항의_구성요소는_인용구가_끝난_자리부터_찾는다():
    # 인용구 안의 "물통"이 아니라 그 뒤의 "물통"을 잡아야 한다
    text = "제1항의 물통에 있어서, 물통은 투명한 화분."
    answer = _answer(2, ["물통"], [1], "제1항의 물통에 있어서")
    result, transport = _split(2, answer, claims={1: CLAIM_1, 2: text})
    assert len(transport.calls) == 1
    (e,) = result.elements
    assert e.status.value == StatusValue.CONFIRMED
    assert e.start == text.index("물통은") and text[e.start : e.end] == "물통"


def test_인용구_안에만_있는_글자는_구성요소로_확인되지_않는다():
    text = "제1항의 물통에 있어서, 뚜껑은 투명한 화분."
    answer = _answer(2, ["제1항의 물통", "뚜껑은 투명한"], [1], "제1항의 물통에 있어서")
    result, _ = _split(2, [answer, answer], claims={1: CLAIM_1, 2: text})
    first, second = result.elements
    assert _is_unverified(first.status, UnverifiedReason.NOT_EXTRACTED)
    assert second.status.value == StatusValue.CONFIRMED


def test_독립항_여부는_모델_판단이고_원문_대조가_없다고_적는다():
    result, _ = _split(1, GOOD_1)
    assert result.depends_on == [] and result.depends_on_status.value == StatusValue.CONFIRMED
    assert "모델 판단" in result.depends_on_status.checked
    assert "원문 대조 없음" in result.depends_on_status.checked


def test_두_번_다_다른_청구항_번호로_답하면_그_청구항은_애매(caplog):
    wrong_claim = _answer(2, [SENSOR, TANK, CONTROL])
    with caplog.at_level(logging.WARNING):
        result, transport = _split(1, [wrong_claim, wrong_claim])
    assert len(transport.calls) == 2
    assert result.claim == 1
    assert _is_unverified(result.status, UnverifiedReason.AMBIGUOUS)
    assert _split_warnings(caplog)


# ---- 맨 앞 인용 문구 전체의 번호 대조 (인용구를 일부만 옮긴 답) ----
def test_인용구를_일부만_옮겨_번호가_빠지면_확인되지_않음(caplog):
    claims = {1: "가.", 2: "나.", 3: "다.", 4: "제1항 내지 제3항 중 어느 한 항에 있어서, 라 화분."}
    partial = _answer(4, ["라 화분"], [3], "제3항 중 어느 한 항에 있어서")
    with caplog.at_level(logging.WARNING):
        result, transport = _split(4, [partial, partial], claims=claims)
    assert len(transport.calls) == 2
    assert result.depends_on is None
    assert _is_unverified(result.depends_on_status, UnverifiedReason.NOT_EXTRACTED)
    assert _split_warnings(caplog)


def test_또는_인용에서_인용구가_뒷_항만_옮겨도_확인되지_않음():
    claims = {1: "가.", 2: "나.", 3: "제1항 또는 제2항에 있어서, 라 화분."}
    partial = _answer(3, ["라 화분"], [2], "제2항에 있어서")
    result, transport = _split(3, [partial, partial], claims=claims)
    assert len(transport.calls) == 2
    assert result.depends_on is None
    assert _is_unverified(result.depends_on_status, UnverifiedReason.NOT_EXTRACTED)


_FIVE = {1: "가.", 2: "나.", 3: "다.", 4: "라.", 5: "마."}


@pytest.mark.parametrize(
    "text",
    [
        "제1항의 물통은 투명한 화분.",
        "제1항 또는 제2항에 있어서, 물통은 투명한 화분.",
        "제1항 내지 제3항 중 어느 한 항에 있어서, 물통은 투명한 화분.",
        "제1항, 제2항 또는 제5항에 있어서, 물통은 투명한 화분.",
        "제 1 항에 있어서, 물통은 투명한 화분.",
        "제1항 및 제2항에 있어서, 물통은 투명한 화분.",
        "제1항과 제2항에 있어서, 물통은 투명한 화분.",
        "제1항 혹은 제2항에 있어서, 물통은 투명한 화분.",
    ],
)
def test_맨_앞이_인용인_원문을_독립항으로_답하면_확인되지_않음(text):
    as_independent = _answer(6, ["물통은 투명한 화분"])
    claims = {**_FIVE, 6: text}
    result, transport = _split(6, [as_independent, as_independent], claims=claims)
    assert len(transport.calls) == 2
    assert result.depends_on is None
    assert _is_unverified(result.depends_on_status, UnverifiedReason.NOT_EXTRACTED)


def test_맨_앞이_인용이_아니고_중간에_제N항이_나오는_독립항은_확인됨():
    text = "물통을 포함하며 이는 제1항과 다른 화분."
    answer = _answer(2, ["물통을 포함하며 이는 제1항과 다른 화분"])
    result, transport = _split(2, answer, claims={1: "가.", 2: text})
    assert len(transport.calls) == 1
    assert result.depends_on == []
    assert result.depends_on_status.value == StatusValue.CONFIRMED


def test_쉼표로_나열한_인용은_번호가_전부_맞으면_확인됨():
    text = "제1항, 제2항 또는 제5항에 있어서, 물통은 투명한 화분."
    answer = _answer(6, ["물통은 투명한 화분"], [1, 2, 5], "제1항, 제2항 또는 제5항에 있어서")
    result, transport = _split(6, answer, claims={**_FIVE, 6: text})
    assert len(transport.calls) == 1
    assert result.depends_on == [1, 2, 5]
    assert result.depends_on_status.value == StatusValue.CONFIRMED


@pytest.mark.parametrize("joiner", ["및", "과", "혹은"])
def test_및_과_혹은으로_이은_인용에서_뒷_항만_옮기면_확인되지_않음(joiner):
    text = f"제1항 {joiner} 제2항에 있어서, 물통은 투명한 화분."
    partial = _answer(3, ["물통은 투명한 화분"], [2], "제2항에 있어서")
    result, transport = _split(3, [partial, partial], claims={1: "가.", 2: "나.", 3: text})
    assert len(transport.calls) == 2
    assert result.depends_on is None
    assert _is_unverified(result.depends_on_status, UnverifiedReason.NOT_EXTRACTED)


@pytest.mark.parametrize("joiner", ["및", "과", "혹은"])
def test_및_과_혹은으로_이은_인용을_전체로_옮기면_확인됨(joiner):
    text = f"제1항 {joiner} 제2항에 있어서, 물통은 투명한 화분."
    full = _answer(3, ["물통은 투명한 화분"], [1, 2], f"제1항 {joiner} 제2항에 있어서")
    result, transport = _split(3, full, claims={1: "가.", 2: "나.", 3: text})
    assert len(transport.calls) == 1
    assert result.depends_on == [1, 2]
    assert result.depends_on_status.value == StatusValue.CONFIRMED
