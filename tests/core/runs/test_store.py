"""메모리 실행 상태 저장소(InMemoryRunStore)와 서버 재시작 정리 (이슈 #57 T1)."""

from datetime import UTC, datetime, timedelta

import pytest

from patent_ai.core.cases.store import InMemoryRunStore
from patent_ai.core.runs.recovery import fail_unfinished_runs
from patent_ai.core.runs.state import InvalidRunTransition, RunError, RunState
from patent_ai.core.runs.store import RunNotFound, SkippedStep

T0 = datetime(2099, 1, 1, tzinfo=UTC)


@pytest.fixture
def store() -> InMemoryRunStore:
    return InMemoryRunStore()


def _running(store: InMemoryRunStore) -> str:
    rid = store.create_queued("oa_1").id
    store.transition(rid, RunState.RUNNING)
    return rid


def test_만들면_queued로_읽힘(store):
    rid = store.create_queued("oa_1").id
    st = store.get_status(rid)
    assert (st.run_id, st.oa_id, st.state) == (rid, "oa_1", RunState.QUEUED)
    assert (st.current_step, st.waiting_for, st.error) == (None, None, None)


def test_없는_실행은_get_status_None_transition_RunNotFound(store):
    assert store.get_status("nope") is None
    with pytest.raises(RunNotFound):
        store.transition("nope", RunState.RUNNING)
    with pytest.raises(RunNotFound):
        store.set_current_step("nope", "x")


def test_허용_전이가_저장됨(store):
    rid = store.create_queued("oa_1").id
    store.transition(rid, RunState.RUNNING, current_step="OA 읽는 중")
    store.set_current_step(rid, "거절이유 정리 중")
    st = store.transition(rid, RunState.WAITING_FOR_HUMAN, waiting_for="application_number")
    assert (st.state, st.current_step, st.waiting_for) == (
        RunState.WAITING_FOR_HUMAN,
        "거절이유 정리 중",
        "application_number",
    )
    # 다시 돌면 기다림 이유는 지워진다
    st = store.transition(rid, RunState.RUNNING)
    assert (st.state, st.waiting_for) == (RunState.RUNNING, None)
    st = store.transition(rid, RunState.FAILED, error=RunError("boom", "실패했다"))
    assert st.error == {"code": "boom", "message": "실패했다"}
    assert store.get_status(rid) == st
    # latest_for_oa(#56)도 같은 줄의 새 상태를 본다
    assert store.latest_for_oa("oa_1").state == "failed"


def test_끝난_실행은_다시_못_바꾸고_값이_그대로(store):
    rid = _running(store)
    store.transition(rid, RunState.SUCCEEDED)
    with pytest.raises(InvalidRunTransition):
        store.transition(rid, RunState.RUNNING)
    assert store.get_status(rid).state == RunState.SUCCEEDED


def test_queued에서_바로_succeeded는_거부(store):
    rid = store.create_queued("oa_1").id
    with pytest.raises(InvalidRunTransition):
        store.transition(rid, RunState.SUCCEEDED)
    assert store.get_status(rid).state == RunState.QUEUED


def test_failed인데_error가_없으면_거부(store):
    rid = _running(store)
    with pytest.raises(InvalidRunTransition):
        store.transition(rid, RunState.FAILED)
    assert store.get_status(rid).state == RunState.RUNNING


def test_unfinished_run_ids는_queued_running만(store):
    queued = store.create_queued("oa_1").id
    running = _running(store)
    waiting = _running(store)
    store.transition(waiting, RunState.WAITING_FOR_HUMAN, waiting_for="x")
    done = _running(store)
    store.transition(done, RunState.SUCCEEDED)
    assert sorted(store.unfinished_run_ids()) == sorted([queued, running])


def test_fail_unfinished_runs(store):
    queued = store.create_queued("oa_1").id
    running = _running(store)
    waiting = _running(store)
    store.transition(waiting, RunState.WAITING_FOR_HUMAN, waiting_for="x")
    done = _running(store)
    store.transition(done, RunState.SUCCEEDED)

    changed = fail_unfinished_runs(store)

    assert sorted(changed) == sorted([queued, running])
    for rid in (queued, running):
        st = store.get_status(rid)
        assert st.state == RunState.FAILED
        assert st.error["code"] == "server_restarted"
        assert st.error["message"].strip()
    assert store.get_status(waiting).state == RunState.WAITING_FOR_HUMAN
    assert store.get_status(done).state == RunState.SUCCEEDED
    # 한 번 더 돌려도 바꿀 게 없다
    assert fail_unfinished_runs(store) == []


def test_시계를_받으면_latest_for_oa가_created_at으로_고름():
    times = iter([T0, T0 + timedelta(seconds=1)])
    s = InMemoryRunStore(clock=lambda: next(times))
    s.create_queued("oa_1")
    second = s.create_queued("oa_1")
    assert s.latest_for_oa("oa_1").id == second.id


def test_record_skipped와_skipped_steps는_기록한_순서로_돌려준다(store):
    rid = _running(store)
    other = _running(store)
    store.record_skipped(rid, "인용문헌 조회", "자료 없음")
    store.record_skipped(other, "다른 실행 단계", "무관")
    store.record_skipped(rid, "법령 조회", "도구 없음")
    assert store.skipped_steps(rid) == [
        SkippedStep("인용문헌 조회", "자료 없음"),
        SkippedStep("법령 조회", "도구 없음"),
    ]
    assert store.skipped_steps("r_없음") == []
