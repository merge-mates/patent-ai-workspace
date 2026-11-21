"""ThreadLauncher (#57): 백그라운드 스레드로 실행기를 돌리고, 실행기가 터져도 failed로 남긴다."""

import threading

from patent_ai.core.runs.launcher import ThreadLauncher
from patent_ai.core.runs.state import RunState
from tests.core.runs.fake_executor import MemoryStatusStore


class Boom:
    def __init__(self, done: threading.Event) -> None:
        self.done = done

    def execute(self, run_id: str, oa_id: str) -> None:
        self.done.set()
        raise RuntimeError("실행기 버그")


def test_실행기가_예외를_던지면_failed_executor_crashed로_남는다():
    store = MemoryStatusStore()
    store.add("r_1")
    done = threading.Event()
    launcher = ThreadLauncher(Boom(done), store)
    launcher("r_1", "oa_1")
    assert done.wait(5)
    for _ in range(500):  # 스레드가 failed를 쓸 때까지 잠깐 기다린다
        if store.get_status("r_1").state == RunState.FAILED:
            break
        threading.Event().wait(0.01)
    status = store.get_status("r_1")
    assert status.state == RunState.FAILED and status.error["code"] == "executor_crashed"
