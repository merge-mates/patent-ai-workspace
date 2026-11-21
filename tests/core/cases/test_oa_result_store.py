"""oa_id 기준 결과 저장·읽기 메모리 구현 (이슈 #57 T1)."""

from datetime import UTC, datetime, timedelta

import pytest

from patent_ai.core.cases.results import InMemoryOAResultStore
from patent_ai.core.cases.store import InMemoryRunStore
from patent_ai.core.runs.state import RunError, RunState
from tests.core.runs.fake_executor import load_oa_result

T0 = datetime(2099, 1, 1, tzinfo=UTC)


def _ticking_clock():
    n = {"i": 0}

    def clock() -> datetime:
        n["i"] += 1
        return T0 + timedelta(seconds=n["i"])

    return clock


def _finish(runs: InMemoryRunStore, run_id: str, new: RunState) -> None:
    runs.transition(run_id, RunState.RUNNING)
    if new == RunState.FAILED:
        runs.transition(run_id, new, error=RunError("boom", "실패"))
    else:
        runs.transition(run_id, new)


@pytest.fixture
def runs() -> InMemoryRunStore:
    return InMemoryRunStore(clock=_ticking_clock())


@pytest.fixture
def results(runs) -> InMemoryOAResultStore:
    return InMemoryOAResultStore(runs, clock=_ticking_clock())


def test_저장_전에는_None(results):
    assert results.latest_succeeded_oa_result("oa_1") is None


def test_succeeded_실행의_결과만_돌려줌(runs, results):
    rid = runs.create_queued("oa_1").id
    results.save_oa_result("oa_1", rid, load_oa_result())
    # 아직 running 전(queued)이라 안 보인다
    assert results.latest_succeeded_oa_result("oa_1") is None
    _finish(runs, rid, RunState.SUCCEEDED)
    got = results.latest_succeeded_oa_result("oa_1")
    assert got.run_id == rid
    assert got.result == load_oa_result()
    # 다른 OA에는 안 보인다
    assert results.latest_succeeded_oa_result("oa_2") is None


def test_failed_실행의_결과는_안_줌(runs, results):
    rid = runs.create_queued("oa_1").id
    results.save_oa_result("oa_1", rid, load_oa_result())
    _finish(runs, rid, RunState.FAILED)
    assert results.latest_succeeded_oa_result("oa_1") is None


def test_두_실행이_succeeded면_나중_실행_것(runs, results):
    first = runs.create_queued("oa_1").id
    second = runs.create_queued("oa_1").id
    for rid in (first, second):
        results.save_oa_result("oa_1", rid, load_oa_result())
        _finish(runs, rid, RunState.SUCCEEDED)
    assert results.latest_succeeded_oa_result("oa_1").run_id == second


def test_저장_시각이_같으면_실행_만든_시각_순():
    runs = InMemoryRunStore(clock=_ticking_clock())
    same = lambda: T0  # noqa: E731
    results = InMemoryOAResultStore(runs, clock=same)
    first = runs.create_queued("oa_1").id
    second = runs.create_queued("oa_1").id
    # 나중 실행의 결과를 먼저 저장해도, 시각이 같으면 runs.created_at이 큰 쪽
    for rid in (second, first):
        results.save_oa_result("oa_1", rid, load_oa_result())
        _finish(runs, rid, RunState.SUCCEEDED)
    assert results.latest_succeeded_oa_result("oa_1").run_id == second
