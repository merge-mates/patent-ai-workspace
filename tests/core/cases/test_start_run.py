"""OA에 실행 만들기 판단 (#57): 진행 중 실행이 있으면 막는다. 메모리 저장소, DB 없음."""

import pytest

from patent_ai.core.cases.start_run import (
    OANotFoundError,
    RunInProgressError,
    create_run_for_oa,
    has_active_run,
)
from patent_ai.core.cases.store import InMemoryCaseAppStore, InMemoryRunStore, NewDocument, now_utc
from patent_ai.core.runs.state import RunError, RunState


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (None, False),
        ("queued", True),
        ("running", True),
        ("waiting_for_human", True),
        ("succeeded", False),
        ("failed", False),
        ("cancelled", False),
    ],
)
def test_진행_중_상태만_True(state, expected):
    assert has_active_run(state) is expected


def _store():
    runs = InMemoryRunStore()
    store = InMemoryCaseAppStore(runs=runs)
    created = store.create_case(NewDocument("p", "h", now_utc()))
    return store, runs, created


def test_없는_OA는_OANotFoundError():
    store, _, _ = _store()
    with pytest.raises(OANotFoundError):
        create_run_for_oa(store, "oa_없음")


def test_진행_중_실행이_있으면_RunInProgressError():
    store, _, created = _store()  # 첫 실행이 queued
    with pytest.raises(RunInProgressError):
        create_run_for_oa(store, created.oa_id)


def test_끝난_실행만_있으면_새_실행을_만든다():
    store, runs, created = _store()
    runs.transition(created.run_id, RunState.FAILED, error=RunError("x", "y"))
    row = create_run_for_oa(store, created.oa_id)
    assert row.id != created.run_id and row.state == "queued" and row.oa_id == created.oa_id
