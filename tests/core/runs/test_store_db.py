"""PostgresRunStatusStore·PostgresOAResultStore 실제 DB 왕복 (make test-db). 끝에 되돌린다.

실행기는 호출마다 새 세션을 열고 커밋한다. 테스트는 한 연결 위에 세션을 여러 개 열어
(커밋은 savepoint 해제) 다른 세션에서 바뀐 값이 보이는지 확인하고, 끝에 바깥 트랜잭션을 되돌린다.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from patent_ai.core.cases.results_pg import PostgresOAResultStore
from patent_ai.core.cases.store import NewDocument
from patent_ai.core.cases.store_pg import PostgresCaseAppStore, PostgresRunStore
from patent_ai.core.runs.recovery import fail_unfinished_runs
from patent_ai.core.runs.state import InvalidRunTransition, RunError, RunState
from patent_ai.core.runs.store import RunNotFound, SkippedStep
from patent_ai.core.runs.store_pg import PostgresRunStatusStore
from patent_ai.db.models import AgentStep, Run
from patent_ai.settings import get_settings
from tests.core.runs.fake_executor import load_oa_result

pytestmark = pytest.mark.db

T0 = datetime(2099, 1, 1, tzinfo=UTC)


@pytest.fixture
def factory():
    engine = create_engine(get_settings().database_url)
    conn = engine.connect()
    outer = conn.begin()
    make = sessionmaker(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield make
    finally:
        outer.rollback()
        conn.close()
        engine.dispose()


def _new_run(factory, sha: str) -> tuple[str, str]:
    """사건·OA·queued 실행을 만들어 커밋하고 (oa_id, run_id)를 돌려준다."""
    with factory() as s:
        created = PostgresCaseAppStore(s).create_case(
            NewDocument(path=f"work/uploads/{sha}.pdf", sha256=sha, received_at=T0)
        )
        s.commit()
    return created.oa_id, created.run_id


def test_만들기_running_succeeded가_다른_세션에서_보임(factory):
    _, rid = _new_run(factory, "db_status_" + "a" * 20)
    store = PostgresRunStatusStore(factory)
    assert store.get_status(rid).state == RunState.QUEUED

    store.transition(rid, RunState.RUNNING, current_step="OA 읽는 중")
    store.set_current_step(rid, "거절이유 정리 중")
    store.transition(rid, RunState.SUCCEEDED)

    # 새 세션(=폴링하는 쪽)에서 읽는다
    with factory() as other:
        run = other.get(Run, rid)
        assert (run.state, run.current_step) == ("succeeded", "거절이유 정리 중")
        assert run.started_at is not None
        assert run.finished_at is not None
    assert store.get_status(rid).state == RunState.SUCCEEDED


def test_거부_전이와_없는_실행(factory):
    _, rid = _new_run(factory, "db_reject_" + "b" * 20)
    store = PostgresRunStatusStore(factory)
    with pytest.raises(InvalidRunTransition):
        store.transition(rid, RunState.SUCCEEDED)  # queued -> succeeded
    assert store.get_status(rid).state == RunState.QUEUED
    store.transition(rid, RunState.RUNNING)
    with pytest.raises(InvalidRunTransition):
        store.transition(rid, RunState.FAILED)  # error 없음
    store.transition(rid, RunState.FAILED, error=RunError("boom", "실패했다"))
    with pytest.raises(InvalidRunTransition):
        store.transition(rid, RunState.RUNNING)  # 끝난 실행
    st = store.get_status(rid)
    assert (st.state, st.error) == (RunState.FAILED, {"code": "boom", "message": "실패했다"})
    assert store.get_status("run_없음") is None
    with pytest.raises(RunNotFound):
        store.transition("run_없음", RunState.RUNNING)


def test_재시작_정리는_queued_running만_failed로(factory):
    _, queued = _new_run(factory, "db_restart_q" + "c" * 20)
    _, running = _new_run(factory, "db_restart_r" + "d" * 20)
    _, waiting = _new_run(factory, "db_restart_w" + "e" * 20)
    store = PostgresRunStatusStore(factory)
    store.transition(running, RunState.RUNNING)
    store.transition(waiting, RunState.RUNNING)
    store.transition(waiting, RunState.WAITING_FOR_HUMAN, waiting_for="application_number")
    mine = {queued, running}
    assert mine <= set(store.unfinished_run_ids())

    changed = fail_unfinished_runs(store)

    assert mine <= set(changed)
    assert waiting not in changed
    for rid in mine:
        st = store.get_status(rid)
        assert (st.state, st.error["code"]) == (RunState.FAILED, "server_restarted")
    assert store.get_status(waiting).state == RunState.WAITING_FOR_HUMAN


def test_결과_저장과_최근_succeeded만_읽음(factory):
    oa_id, first = _new_run(factory, "db_result_" + "f" * 20)
    store = PostgresRunStatusStore(factory)
    results = PostgresOAResultStore(factory)
    assert results.latest_succeeded_oa_result(oa_id) is None

    # 첫 실행: 결과를 저장했지만 실패 -> 안 보인다
    results.save_oa_result(oa_id, first, load_oa_result())
    store.transition(first, RunState.RUNNING)
    store.transition(first, RunState.FAILED, error=RunError("boom", "실패했다"))
    assert results.latest_succeeded_oa_result(oa_id) is None

    # 둘째 실행: 성공 -> 보인다
    with factory() as s:
        second = PostgresRunStore(s).create_queued(oa_id).id
        s.commit()
    results.save_oa_result(oa_id, second, load_oa_result())
    store.transition(second, RunState.RUNNING)
    store.transition(second, RunState.SUCCEEDED)
    got = results.latest_succeeded_oa_result(oa_id)
    assert got.run_id == second
    assert got.result == load_oa_result()


def test_record_skipped_왕복은_agent_steps에_skipped로_남는다(factory):
    _, rid = _new_run(factory, "db_skipped_" + "f" * 20)
    store = PostgresRunStatusStore(factory)
    store.record_skipped(rid, "인용문헌 조회", "자료 없음")
    store.record_skipped(rid, "법령 조회", "도구 없음")
    assert store.skipped_steps(rid) == [
        SkippedStep("인용문헌 조회", "자료 없음"),
        SkippedStep("법령 조회", "도구 없음"),
    ]
    with factory() as other:
        rows = list(other.scalars(select(AgentStep).where(AgentStep.run_id == rid)))
        assert {(r.step_kind, r.outcome) for r in rows} == {("code_tool", "skipped")}
