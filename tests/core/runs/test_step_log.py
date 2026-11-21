"""지휘 단계 기록을 한 곳(step_log)으로만 보내는지 본다 (이슈 #216 T1).
확인: uv run pytest tests/core/runs -k step_recorder   (네트워크·키·DB 없음)
"""

import threading

from patent_ai.core.agents.steps import MemoryStepRecorder, StepRecord
from patent_ai.core.cases.results import InMemoryOAResultStore
from patent_ai.core.cases.step_results import InMemoryStepResultStore
from patent_ai.core.runs.cancel import CancelRegistry
from patent_ai.core.runs.run_case_executor import RunCaseExecutor
from patent_ai.core.runs.state import RunState
from patent_ai.core.runs.store import RunLogWriteFailed
from tests.core.run_case_fakes import CHECKED_ON, fake_ctx, real_config, wire
from tests.core.runs.fake_executor import MemoryStatusStore
from tests.core.runs.test_run_case_executor import OID, RID, _Cases, _Inputs


def _run(tmp_path, step_log=None):
    store = MemoryStatusStore()
    store.add(RID, OID)
    kwargs = {} if step_log is None else {"step_log": step_log}
    RunCaseExecutor(
        store=store,
        registry=CancelRegistry(),
        oa_results=InMemoryOAResultStore(store),
        step_results=InMemoryStepResultStore(),
        inputs=_Inputs(tmp_path),
        cases=_Cases(),
        config_path=real_config(tmp_path),
        make_ctx=fake_ctx,
        today=lambda: CHECKED_ON,
        lock=threading.Lock(),
        **kwargs,
    ).execute(RID, OID)
    return store


def test_step_recorder를_주면_ok와_skipped가_모두_기록기로_가고_저장소에는_안_쓴다(
    tmp_path, monkeypatch
):
    wire(monkeypatch)
    rec = MemoryStepRecorder()
    store = _run(tmp_path, rec)
    assert store.get_status(RID).state == RunState.SUCCEEDED
    outcomes = {(r.tool_name, r.outcome) for r in rec.records}
    assert ("read_oa", "ok") in outcomes and ("run_f2", "skipped") in outcomes
    assert store.skipped_steps(RID) == []  # 두 곳에 쓰지 않는다


def test_step_recorder를_안_주면_skipped가_저장소에_남는다(tmp_path, monkeypatch):
    wire(monkeypatch)
    store = _run(tmp_path)
    assert [s.step for s in store.skipped_steps(RID)] == ["run_f2"]


def test_step_recorder_쓰기가_실패하면_record_failed로_끝나고_원문은_안_보인다(
    tmp_path, monkeypatch
):
    wire(monkeypatch)

    class Broken:
        def record(self, step: StepRecord) -> None:
            raise RunLogWriteFailed("비밀 연결문자열 postgres://x")

    store = _run(tmp_path, Broken())
    st = store.get_status(RID)
    assert st.state == RunState.FAILED and st.error["code"] == "record_failed"
    assert "비밀" not in st.error["message"]
    assert "실행 기록 저장 실패" in st.error["message"]


# --- T2: 모델 호출 기록 (CallRecord) ---------------------------------------------------


def test_call_recorder_쓰기가_실패하면_record_failed로_끝나고_원문은_안_보인다(
    tmp_path, monkeypatch
):
    from patent_ai.core.llm.limits import CallBudget, RunContext
    from tests.core.run_case_fakes import FakeTransport, _responses

    wire(monkeypatch)

    class BrokenCalls:
        def record(self, rec) -> None:
            raise RunLogWriteFailed("비밀 연결문자열 postgres://x")

    def ctx(run_id: str) -> RunContext:
        return RunContext(
            run_id=run_id,
            budget=CallBudget(),
            recorder=BrokenCalls(),
            transport=FakeTransport(_responses()),
        )

    store = MemoryStatusStore()
    store.add(RID, OID)
    RunCaseExecutor(
        store=store,
        registry=CancelRegistry(),
        oa_results=InMemoryOAResultStore(store),
        step_results=InMemoryStepResultStore(),
        inputs=_Inputs(tmp_path),
        cases=_Cases(),
        config_path=real_config(tmp_path),
        make_ctx=ctx,
        today=lambda: CHECKED_ON,
        lock=threading.Lock(),
    ).execute(RID, OID)
    st = store.get_status(RID)
    assert st.state == RunState.FAILED and st.error["code"] == "record_failed"
    assert "비밀" not in st.error["message"]


def test_call_recorder_서버_실행맥락은_PostgresCallRecorder이고_실행마다_새_객체다():
    from patent_ai.api import deps
    from patent_ai.core.runs.step_log_pg import PostgresCallRecorder

    a = deps._new_run_context("r_a")
    b = deps._new_run_context("r_b")
    assert isinstance(a.recorder, PostgresCallRecorder)
    assert a.recorder is not b.recorder  # records가 실행끼리 안 섞인다
