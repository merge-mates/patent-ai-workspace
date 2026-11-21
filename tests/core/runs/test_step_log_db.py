"""PostgresStepRecorder 실제 DB 왕복 (make test-db). 끝에 되돌린다."""

import pytest
from sqlalchemy import select

from patent_ai.core.agents.steps import StepRecord
from patent_ai.core.runs.step_log_pg import PostgresStepRecorder
from patent_ai.core.runs.store import RunLogWriteFailed, SkippedStep
from patent_ai.core.runs.store_pg import PostgresRunStatusStore
from patent_ai.db.models import AgentStep
from tests.core.runs.test_store_db import _new_run, factory  # noqa: F401

pytestmark = pytest.mark.db


def _step(rid, tool, outcome, **kw):
    return StepRecord(
        run_id=rid, step_kind="code_tool", tool_name=tool, reason="이유", outcome=outcome, **kw
    )


def test_step_recorder_네_결과가_다른_세션에서_기록_순서대로_보인다(factory):  # noqa: F811
    _, rid = _new_run(factory, "db_steplog_" + "a" * 20)
    rec = PostgresStepRecorder(factory)
    rec.record(_step(rid, "read_oa", "ok", result_status="confirmed", model_call_count=2))
    rec.record(_step(rid, "run_f3", "failed"))
    rec.record(_step(rid, "run_f4", "waiting", result_id="x_1"))
    rec.record(_step(rid, "run_f2", "skipped"))
    with factory() as other:
        rows = list(
            other.scalars(select(AgentStep).where(AgentStep.run_id == rid).order_by(AgentStep.id))
        )
    assert [(r.tool_name, r.outcome) for r in rows] == [
        ("read_oa", "ok"),
        ("run_f3", "failed"),
        ("run_f4", "waiting"),
        ("run_f2", "skipped"),
    ]
    first = rows[0]
    assert (first.step_kind, first.reason, first.result_status, first.model_call_count) == (
        "code_tool",
        "이유",
        "confirmed",
        2,
    )
    assert rows[2].result_id == "x_1"


def test_step_recorder_skipped_줄을_상태_저장소가_읽는다(factory):  # noqa: F811
    _, rid = _new_run(factory, "db_steplog_" + "b" * 20)
    PostgresStepRecorder(factory).record(_step(rid, "run_f2", "skipped"))
    PostgresStepRecorder(factory).record(_step(rid, "read_oa", "ok"))
    assert PostgresRunStatusStore(factory).skipped_steps(rid) == [SkippedStep("run_f2", "이유")]


def test_step_recorder_없는_run_id면_RunLogWriteFailed(factory):  # noqa: F811
    with pytest.raises(RunLogWriteFailed):
        PostgresStepRecorder(factory).record(_step("r_없음", "read_oa", "ok"))


# --- T2: 모델 호출 기록 ----------------------------------------------------------------


def _call(rid, outcome, **kw):
    from patent_ai.core.llm.limits import CallRecord

    base = dict(
        run_id=rid,
        step="read_oa",
        model="m-1",
        input_tokens=10,
        output_tokens=5,
        cost=0.0123,
        elapsed_ms=200,
        from_cache=False,
        attempt=1,
        outcome=outcome,
        transport_try=1,
        stop_reason="end_turn",
    )
    base.update(kw)
    return CallRecord(**base)


def test_call_recorder_두_호출이_다른_세션에서_순서대로_칸이_맞게_보인다(factory):  # noqa: F811
    from decimal import Decimal

    from patent_ai.core.runs.step_log_pg import PostgresCallRecorder

    _, rid = _new_run(factory, "db_calllog_" + "a" * 20)
    rec = PostgresCallRecorder(factory)
    ok = _call(rid, "ok")
    bad = _call(
        rid,
        "transport_error",
        input_tokens=None,
        output_tokens=None,
        cost=None,
        attempt=2,
        transport_try=2,
        stop_reason=None,
    )
    rec.record(ok)
    rec.record(bad)
    assert rec.records == [ok, bad]
    with factory() as other:
        rows = list(
            other.scalars(select(AgentStep).where(AgentStep.run_id == rid).order_by(AgentStep.id))
        )
    assert [(r.step_kind, r.tool_name, r.outcome) for r in rows] == [
        ("model_call", "read_oa", "ok"),
        ("model_call", "read_oa", "transport_error"),
    ]
    a, b = rows
    assert (a.model, a.input_tokens, a.output_tokens, a.cost) == ("m-1", 10, 5, Decimal("0.012300"))
    assert (a.elapsed_ms, a.from_cache, a.attempt, a.transport_try, a.stop_reason) == (
        200,
        False,
        1,
        1,
        "end_turn",
    )
    assert (b.input_tokens, b.output_tokens, b.cost, b.stop_reason) == (None, None, None, None)
    assert (b.attempt, b.transport_try) == (2, 2)


def test_call_recorder_없는_run_id면_RunLogWriteFailed이고_records에_안_붙는다(factory):  # noqa: F811
    from patent_ai.core.runs.step_log_pg import PostgresCallRecorder

    rec = PostgresCallRecorder(factory)
    with pytest.raises(RunLogWriteFailed):
        rec.record(_call("r_없음", "ok"))
    assert rec.records == []
