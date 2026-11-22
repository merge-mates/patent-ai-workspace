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


# --- 조립: 서버 실행 한 번이 지휘 단계와 모델 호출을 같이 남긴다 ------------------------------


class _Saved:
    """결과 받는 곳 (이 테스트는 agent_steps만 본다)."""

    def save_oa_result(self, oa_id, run_id, result):
        pass

    def save_step_result(self, oa_id, run_id, result):
        return "sres_가짜"


def _execute(factory, tmp_path, monkeypatch, tag, step_results=None):  # noqa: F811
    """서버(deps.py)와 같이 실제 DB 기록기로 실행 한 바퀴. (store, run_id)를 돌려준다."""
    import threading

    from patent_ai.core.cases.human_inputs import InMemoryHumanInputStore
    from patent_ai.core.cases.selections import InMemorySelectionStore
    from patent_ai.core.llm.limits import CallBudget, RunContext
    from patent_ai.core.llm.transport import FakeTransport
    from patent_ai.core.runs.cancel import CancelRegistry
    from patent_ai.core.runs.run_case_executor import RunCaseExecutor
    from patent_ai.core.runs.step_log_pg import PostgresCallRecorder
    from tests.core.agents.test_fixed_order_f3_f4 import _responses
    from tests.core.run_case_fakes import CHECKED_ON, real_config, wire
    from tests.core.runs.test_run_case_executor import _CaseFill, _Cases, _Inputs

    wire(monkeypatch)
    oa_id, rid = _new_run(factory, "db_steplog_" + tag * 20)
    store = PostgresRunStatusStore(factory)
    # 단계는 PostgresStepRecorder, 모델 호출은 PostgresCallRecorder
    RunCaseExecutor(
        store=store,
        registry=CancelRegistry(),
        oa_results=_Saved(),
        step_results=step_results or _Saved(),
        case_fill=_CaseFill(),
        inputs=_Inputs(tmp_path),
        cases=_Cases(),
        config_path=real_config(tmp_path),
        make_ctx=lambda r: RunContext(
            run_id=r,
            budget=CallBudget(),
            recorder=PostgresCallRecorder(factory),
            transport=FakeTransport(_responses()),
        ),
        today=lambda: CHECKED_ON,
        selections=InMemorySelectionStore(),
        human=InMemoryHumanInputStore(),
        lock=threading.Lock(),
        step_log=PostgresStepRecorder(factory),
    ).execute(rid, oa_id)
    return store, rid


def test_step_recorder_call_recorder_실행_한_번이_단계와_모델_호출을_같이_남긴다(
    factory,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    from patent_ai.core.runs.state import RunState

    store, rid = _execute(factory, tmp_path, monkeypatch, "c")
    assert store.get_status(rid).state == RunState.SUCCEEDED

    # 실행이 끝난 뒤 새 세션에서: 어느 단계가 돌았고 몇 번 불렀는지 보인다
    with factory() as other:
        rows = list(
            other.scalars(select(AgentStep).where(AgentStep.run_id == rid).order_by(AgentStep.id))
        )
    steps = [r for r in rows if r.step_kind != "model_call"]
    calls = [r for r in rows if r.step_kind == "model_call"]
    assert ("read_oa", "ok") in {(r.tool_name, r.outcome) for r in steps}
    # F2도 돈다(#28, 모델 호출 0번). 넘김 줄이 DB로 가는 것은 위 skipped 테스트가 본다
    assert ("run_f2", "ok") in {(r.tool_name, r.outcome) for r in steps}
    assert calls, "모델 호출 줄이 없다"
    # 단계 기록의 호출 수(model_call_count)가 셈할 수 있게 채워지고, 합이 전송 줄 수와 같다
    sent = {"ok", "invalid_output", "output_truncated", "transport_error"}
    counted = [
        r.model_call_count for r in steps if r.outcome == "ok" and r.step_kind == "code_tool"
    ]
    assert all(c is not None for c in counted)
    assert sum(counted) == sum(1 for c in calls if c.outcome in sent)
    assert store.skipped_steps(rid) == []


# --- #267: 결과를 저장한 단계에 step_results ID 붙이기 -----------------------------------


def test_link_result는_그_도구의_ok_줄에만_ID를_쓰고_skipped_failed는_NULL(factory):  # noqa: F811
    _, rid = _new_run(factory, "db_steplog_" + "d" * 20)
    rec = PostgresStepRecorder(factory)
    rec.record(_step(rid, "run_f3", "failed"))
    rec.record(_step(rid, "run_f3", "ok"))
    rec.record(_step(rid, "run_f2", "skipped"))
    rec.link_result(rid, "run_f3", "sres_1")
    rec.link_result(rid, "run_f2", "sres_2")  # 넘긴 단계는 붙일 줄이 없다
    with factory() as other:
        rows = list(
            other.scalars(select(AgentStep).where(AgentStep.run_id == rid).order_by(AgentStep.id))
        )
    assert [(r.tool_name, r.outcome, r.result_id) for r in rows] == [
        ("run_f3", "failed", None),
        ("run_f3", "ok", "sres_1"),
        ("run_f2", "skipped", None),
    ]


def test_실행_뒤_결과를_저장한_단계의_result_id가_그_step_results_줄을_가리킨다(
    factory,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    from patent_ai.core.cases.step_results_pg import PostgresStepResultStore
    from patent_ai.core.runs.state import RunState
    from patent_ai.db.models import StepResultRow

    store, rid = _execute(
        factory, tmp_path, monkeypatch, "e", step_results=PostgresStepResultStore(factory)
    )
    assert store.get_status(rid).state == RunState.SUCCEEDED
    with factory() as other:
        steps = list(
            other.scalars(
                select(AgentStep).where(
                    AgentStep.run_id == rid, AgentStep.step_kind != "model_call"
                )
            )
        )
        saved = {
            r.kind: r.id
            for r in other.scalars(select(StepResultRow).where(StepResultRow.run_id == rid))
        }
    assert set(saved) == {"f2", "f3", "f4"}
    linked = {r.tool_name: r.result_id for r in steps if r.result_id is not None}
    assert linked == {"run_f2": saved["f2"], "run_f3": saved["f3"], "run_f4": saved["f4"]}
