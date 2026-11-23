"""청구항 나누기 호출 실패는 그 청구항만 보류한다 (이슈 #317, #166 (가)와 같은 규칙).

가짜 응답(FakeTransport)으로: 청구항 2의 첫 답이 원문 대조에 떨어지고, 검사 오류를 붙여 다시
부른 답이 JSON이 아니면 실행 전체를 멈추지 않는다. 청구항 2만 보류 + 확인되지 않음 + 이유로
남기고, 청구항 1은 끝까지 대비한다. 모든 청구항이 실패하면 원래 예외를 그대로 올린다.
호출 상한은 대비·명확성처럼 실패가 아니라 limit_reached로 보류한다 (ADR 0003).
"""

import pytest

from patent_ai.core.llm.config import load_step_config
from patent_ai.core.llm.errors import ModelOutputInvalid
from patent_ai.core.llm.transport import TransportError, TransportResponse
from patent_ai.core.schemas.common import Flag, StatusValue, UnverifiedReason
from tests.core.f3 import scenario
from tests.core.f3.run_helpers import run_scenario

# 검사 오류를 붙여 다시 부른 답이 코드 블록으로 감싸여 첫 글자부터 JSON이 아님
FENCED = TransportResponse('```json\n{"claim": 2}\n```', 100, 20)
EMPTY = TransportResponse("", 100, 0)
# 원문은 "제1항에 있어서"로 시작하는데 독립항으로 답함 -> 원문 대조에 떨어짐 (JSON은 맞음)
WRONG_DEPENDS = scenario._split(2, [scenario.MODULE])
SPLIT2_TASK = "f3_split:oa_1:claim2:call_failed"


def _held(result, task):
    return next((h for h in result.held_tasks if h.task == task), None)


def test_다시_부른_답이_JSON이_아니면_그_청구항만_보류하고_나머지는_끝까지_한다():
    answers = scenario.responses()
    answers["f3.split_elements"] = [
        scenario._split(1, [scenario.SENSOR, scenario.TANK]),
        WRONG_DEPENDS,
        FENCED,
    ]
    result, _ = run_scenario(answers=answers)
    held = _held(result, SPLIT2_TASK)
    assert held is not None
    assert held.waiting_for.startswith("원문 확인 필요")
    assert "ModelOutputInvalid" in held.waiting_for  # 이유가 남는다
    # 청구항 1은 끝까지 대비한다 (청구항 2는 혼자 단위로 남지만 구성요소가 없어 대비 보류)
    assert [t.unit_id for t in result.comparisons] == ["oa_1:29-2:c1"]
    # 조용히 성공으로 두지 않는다 (이유는 결과 전체 status가 고른 값. 보류는 위에서 봄)
    assert result.status.value == StatusValue.UNVERIFIED


def test_독립항_나누기가_실패하면_그를_인용하는_청구항도_혼자_단위로_남고_확인되지_않음이다():
    # 독립항 1의 두 답이 모두 비어 실패하고 종속항 2는 나뉜다 (인용 관계 [1]).
    # build_units는 인용 관계를 끝까지 모르는 청구항을 빼지 않고 혼자 단위로 둔다 (units.py)
    answers = scenario.responses()
    answers["f3.split_elements"] = [
        EMPTY,
        EMPTY,
        scenario._split(2, [scenario.MODULE], [1], "제1항에 있어서"),
    ]
    answers["f3.compare"] = answers["f3.compare"][1:]  # 청구항 1은 구성요소가 없어 안 부름
    result, _ = run_scenario(answers=answers)
    assert _held(result, "f3_split:oa_1:claim1:call_failed") is not None
    units = {u.unit_id: u for u in result.units}
    # 진보성은 독립항 묶음이 아니라 청구항마다 혼자 단위, 명확성 단위도 남는다
    assert sorted(units) == ["oa_1:29-2:c1", "oa_1:29-2:c2", "oa_1:42-4-2:c2"]
    alone = units["oa_1:29-2:c2"]
    assert alone.claims == [2] and alone.representative_claim == 2
    for unit in units.values():
        assert unit.status.value == StatusValue.UNVERIFIED
        assert unit.status.reason == UnverifiedReason.INPUT_UNVERIFIED
        assert Flag.NEEDS_HUMAN_REVIEW in unit.flags
    # 청구항 1 단위는 대비하지 못해 보류, 종속항 2는 부모 구성요소 없이 혼자 대비된다
    assert _held(result, "f3_compare:oa_1:29-2:c1:claim1") is not None
    assert [t.unit_id for t in result.comparisons] == ["oa_1:29-2:c2"]
    assert result.status.value == StatusValue.UNVERIFIED


def test_두_답이_모두_JSON이_아니어도_그_청구항만_보류한다():
    answers = scenario.responses()
    answers["f3.split_elements"] = [
        scenario._split(1, [scenario.SENSOR, scenario.TANK]),
        EMPTY,
        EMPTY,
    ]
    result, _ = run_scenario(answers=answers)
    assert _held(result, SPLIT2_TASK) is not None
    assert result.status.value == StatusValue.UNVERIFIED


def test_모든_청구항_나누기가_실패하면_원래_예외를_그대로_올린다():
    answers = scenario.responses()
    answers["f3.split_elements"] = [EMPTY, EMPTY, EMPTY, EMPTY]
    with pytest.raises(ModelOutputInvalid):
        run_scenario(answers=answers)


def test_나누기_호출_상한에_닿으면_실패가_아니라_limit_reached로_보류한다():
    ctx, transport = scenario.context()
    cap = load_step_config("f3.split_elements").max_model_calls
    for _ in range(cap):  # 이 단계 호출을 상한만큼 이미 쓴 것으로 센다
        ctx.budget.add(ctx.run_id, "f3.split_elements", 0)
    result, _ = run_scenario(ctx=ctx, transport=transport)
    for claim in (1, 2):
        held = _held(result, f"f3_split:oa_1:claim{claim}:limit_reached")
        assert held is not None and "max_model_calls" in held.waiting_for
    assert result.comparisons == []
    assert result.status.value == StatusValue.UNVERIFIED


def test_나누기_전송_오류도_그_청구항만_보류한다():
    answers = scenario.responses()
    answers["f3.split_elements"] = [
        scenario._split(1, [scenario.SENSOR, scenario.TANK]),
        TransportError("연결 끊김", retryable=False),
    ]
    result, _ = run_scenario(answers=answers)
    held = _held(result, SPLIT2_TASK)
    assert held is not None and "ModelCallFailed" in held.waiting_for
    assert result.status.value == StatusValue.UNVERIFIED
