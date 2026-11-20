"""취소 요청. 취소 표시는 메모리(실행 id별 Event)에 두고, 상태는 DB(저장소)에 쓴다.

- queued / waiting_for_human: 도는 스레드가 없으니 바로 cancelled.
- running: 표시만 한다. 도는 쪽이 지금 단계가 끝난 뒤 cancelled로 바꾼다.
- 끝나는 순간과 겹치면 저장소에 먼저 쓴 쪽이 이긴다 (끝난 실행은 안 바뀌는 규칙).
"""

import threading

from patent_ai.core.runs.state import FINISHED_STATES, InvalidRunTransition, RunState
from patent_ai.core.runs.store import RunNotFound, RunStatus, RunStatusStore


class RunAlreadyFinished(Exception):
    """이미 끝난 실행은 취소할 수 없다 (API는 409 run_already_finished)."""


class CancelRegistry:
    """실행 id별 취소 표시. 여러 스레드에서 써도 안전하다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, threading.Event] = {}

    def request(self, run_id: str) -> None:
        with self._lock:
            self._events.setdefault(run_id, threading.Event()).set()

    def is_requested(self, run_id: str) -> bool:
        with self._lock:
            event = self._events.get(run_id)
        return event is not None and event.is_set()

    def forget(self, run_id: str) -> None:
        with self._lock:
            self._events.pop(run_id, None)


def request_cancel(run_id: str, store: RunStatusStore, registry: CancelRegistry) -> RunStatus:
    status = store.get_status(run_id)
    if status is None:
        raise RunNotFound(run_id)
    if status.state in FINISHED_STATES:
        raise RunAlreadyFinished(run_id)
    if status.state == RunState.RUNNING:
        registry.request(run_id)
        return status
    # queued, waiting_for_human: 바로 cancelled
    try:
        updated = store.transition(run_id, RunState.CANCELLED)
    except InvalidRunTransition:
        # 읽은 직후 상태가 바뀐 경우 (예: queued -> running). 다시 읽어 판단한다
        latest = store.get_status(run_id)
        if latest is None:
            raise RunNotFound(run_id) from None
        if latest.state in FINISHED_STATES:
            raise RunAlreadyFinished(run_id) from None
        registry.request(run_id)
        return latest
    registry.forget(run_id)
    return updated
