"""StepRecord의 limit_reached 값 (#241). 확인: uv run pytest tests/core/agents -k step_record"""

from patent_ai.core.agents.steps import StepRecord


def _rec(outcome: str) -> StepRecord:
    return StepRecord(
        run_id="r_1",
        step_kind="code_tool",
        tool_name="read_oa",
        reason="limit_reached: read_oa 호출 상한 max_model_calls 2에 닿음",
        outcome=outcome,
    )


def test_step_record_limit_reached는_넘긴_이유로_읽힌다():
    r = _rec("limit_reached")
    assert r.skipped_reason == r.reason


def test_step_record_ok는_넘긴_이유가_없다():
    assert _rec("ok").skipped_reason is None
