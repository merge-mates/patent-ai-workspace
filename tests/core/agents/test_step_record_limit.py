"""StepRecord의 limit_reached 값 (#241). 확인: uv run pytest tests/core/agents -k step_record"""

from patent_ai.core.agents.steps import StepRecord


def _rec(outcome: str, kind: str = "code_tool") -> StepRecord:
    return StepRecord(
        run_id="r_1",
        step_kind=kind,
        tool_name="read_oa",
        reason="limit_reached: read_oa 호출 상한 max_model_calls 2에 닿음",
        outcome=outcome,
    )


def test_step_record_limit_reached는_넘긴_이유로_읽힌다():
    r = _rec("limit_reached")
    assert r.skipped_reason == r.reason


def test_step_record_ok는_넘긴_이유가_없다():
    assert _rec("ok").skipped_reason is None


def test_step_record_decide_줄은_상한이어도_넘긴_이유가_없다():
    # decide 줄은 넘긴 단계 목록에 안 나온다 (단계마다 code_tool 줄이 따로 남는다)
    assert _rec("limit_reached", "decide").skipped_reason is None
