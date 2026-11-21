"""실행기·취소 테스트. 기대값은 이슈 #57 '정한 것'에서 가져왔다."""

import pytest

from patent_ai.core.runs.cancel import CancelRegistry, RunAlreadyFinished, request_cancel
from patent_ai.core.runs.executor import NotConnectedExecutor, Skip, Step
from patent_ai.core.runs.state import RunState
from patent_ai.core.runs.store import RunNotFound, SkippedStep
from tests.core.runs.fake_executor import (
    FailingSink,
    MemorySink,
    MemoryStatusStore,
    cancelling_step,
    load_oa_result,
    make_fake_executor,
    raising_step,
    recording_step,
    skipping_step,
    waiting_step,
)

RID = "r1"


@pytest.fixture
def store() -> MemoryStatusStore:
    s = MemoryStatusStore()
    s.add(RID)
    return s


@pytest.fixture
def registry() -> CancelRegistry:
    return CancelRegistry()


@pytest.fixture
def sink() -> MemorySink:
    return MemorySink()


def test_성공하면_succeeded_이고_OA_정리가_저장된다(store, registry, sink):
    make_fake_executor(store, registry, sink).execute(RID, "oa_1")
    assert store.get_status(RID).state == RunState.SUCCEEDED
    assert len(sink.saved) == 1
    oa_id, run_id, result = sink.saved[0]
    assert (oa_id, run_id) == ("oa_1", RID)
    assert result == load_oa_result()


def test_단계마다_current_step이_바뀐다(store, registry, sink):
    make_fake_executor(store, registry, sink).execute(RID, "oa_1")
    assert store.step_history[RID] == ["OA 읽는 중", "거절이유 정리 중"]


def test_단계에서_예외가_나면_failed와_이유가_남고_저장_안_된다(store, registry, sink):
    log: list[str] = []
    steps = [
        raising_step("OA 읽는 중", ValueError("깨진 PDF")),
        recording_step("거절이유 정리 중", log),
    ]
    make_fake_executor(store, registry, sink, steps).execute(RID, "oa_1")
    st = store.get_status(RID)
    assert st.state == RunState.FAILED
    assert st.error["code"] == "step_failed"
    assert "OA 읽는 중" in st.error["message"]
    assert "깨진 PDF" in st.error["message"]
    assert sink.saved == []
    assert log == []


def test_도중_취소하면_남은_단계_안_돌고_cancelled(store, registry, sink):
    log: list[str] = []
    steps = [
        cancelling_step("OA 읽는 중", registry, RID, log),
        recording_step("거절이유 정리 중", log),
    ]
    make_fake_executor(store, registry, sink, steps).execute(RID, "oa_1")
    assert store.get_status(RID).state == RunState.CANCELLED
    assert log == ["OA 읽는 중"]
    assert sink.saved == []


def test_마지막_단계_중_취소해도_cancelled이고_저장_안_된다(store, registry, sink):
    steps = [cancelling_step("거절이유 정리 중", registry, RID)]
    make_fake_executor(store, registry, sink, steps).execute(RID, "oa_1")
    assert store.get_status(RID).state == RunState.CANCELLED
    assert sink.saved == []


def test_queued_취소는_바로_cancelled이고_그_뒤_실행기는_단계를_안_돈다(store, registry, sink):
    st = request_cancel(RID, store, registry)
    assert st.state == RunState.CANCELLED
    log: list[str] = []
    make_fake_executor(store, registry, sink, [recording_step("a", log)]).execute(RID, "oa_1")
    assert store.get_status(RID).state == RunState.CANCELLED
    assert log == []
    assert sink.saved == []


def test_running_취소는_표시만_하고_상태는_그대로(store, registry):
    store.transition(RID, RunState.RUNNING)
    st = request_cancel(RID, store, registry)
    assert st.state == RunState.RUNNING
    assert registry.is_requested(RID)


def test_사람_기다림이면_waiting_for가_남고_저장_안_된다(store, registry, sink):
    steps = [waiting_step("OA 읽는 중", "application_number")]
    make_fake_executor(store, registry, sink, steps).execute(RID, "oa_1")
    st = store.get_status(RID)
    assert st.state == RunState.WAITING_FOR_HUMAN
    assert st.waiting_for == "application_number"
    assert sink.saved == []


def test_waiting_for_human_취소는_바로_cancelled(store, registry):
    store.transition(RID, RunState.RUNNING)
    store.transition(RID, RunState.WAITING_FOR_HUMAN, waiting_for="application_number")
    assert request_cancel(RID, store, registry).state == RunState.CANCELLED


@pytest.mark.parametrize("state", [RunState.SUCCEEDED, RunState.FAILED, RunState.CANCELLED])
def test_끝난_실행_취소는_RunAlreadyFinished(registry, state):
    s = MemoryStatusStore()
    s.add("x", state=state)
    with pytest.raises(RunAlreadyFinished):
        request_cancel("x", s, registry)


def test_없는_실행_취소는_RunNotFound(store, registry):
    with pytest.raises(RunNotFound):
        request_cancel("없음", store, registry)


def test_결과_저장이_실패하면_failed_result_save_failed(store, registry):
    make_fake_executor(store, registry, FailingSink()).execute(RID, "oa_1")
    st = store.get_status(RID)
    assert st.state == RunState.FAILED
    assert st.error["code"] == "result_save_failed"


def test_끝나면_취소_표시가_지워진다(store, registry, sink):
    steps = [cancelling_step("OA 읽는 중", registry, RID)]
    make_fake_executor(store, registry, sink, steps).execute(RID, "oa_1")
    assert not registry.is_requested(RID)


def test_연결_전_실행기는_failed_executor_not_connected(store):
    NotConnectedExecutor(store).execute(RID, "oa_1")
    st = store.get_status(RID)
    assert st.state == RunState.FAILED
    assert st.error == {"code": "executor_not_connected", "message": "지휘 에이전트 연결 전"}


def test_취소가_시작과_겹쳐도_결과가_저장되지_않는다(store, registry, sink):
    # 취소 요청이 queued를 읽은 직후 실행기가 running으로 바꾼 경우를 흉내 낸다
    real_get = store.get_status
    stale = store.get_status(RID)
    calls = {"n": 0}

    def stale_once(run_id):
        calls["n"] += 1
        return stale if calls["n"] == 1 else real_get(run_id)

    def cancel_during_first_step() -> None:
        store.get_status = stale_once  # 첫 읽기는 옛 queued 값
        request_cancel(RID, store, registry)
        store.get_status = real_get

    steps = [Step("OA 읽는 중", cancel_during_first_step), Step("거절이유 정리 중", lambda: None)]
    make_fake_executor(store, registry, sink, steps).execute(RID, "oa_1")
    assert store.get_status(RID).state == RunState.CANCELLED
    assert sink.saved == []


def test_넘긴_단계가_있어도_다음_단계가_돌고_succeeded(store, registry, sink):
    log: list[str] = []
    steps = [
        skipping_step("인용문헌 조회", "인용문헌 자료 없음"),
        recording_step("거절이유 정리 중", log),
    ]
    make_fake_executor(store, registry, sink, steps).execute(RID, "oa_1")
    assert store.get_status(RID).state == RunState.SUCCEEDED
    assert log == ["거절이유 정리 중"]
    assert len(sink.saved) == 1
    assert store.skipped_steps(RID) == [SkippedStep("인용문헌 조회", "인용문헌 자료 없음")]


def test_넘긴_단계가_없으면_skipped_steps는_빈_목록(store, registry, sink):
    make_fake_executor(store, registry, sink).execute(RID, "oa_1")
    assert store.skipped_steps(RID) == []


def test_빈_이유의_Skip은_만들_수_없다():
    with pytest.raises(ValueError):
        Skip("")
