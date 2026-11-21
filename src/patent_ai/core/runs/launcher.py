"""만든 실행을 실행기에 넘기는 방법 (launcher). API는 커밋 뒤에 launcher를 부른다.

앱 기본은 백그라운드 스레드(daemon). 서버가 꺼지면 스레드도 사라지므로
남은 실행은 다음에 켜질 때 recovery.fail_unfinished_runs가 정리한다.
테스트는 그 자리에서 바로 도는 launcher를 끼운다.
"""

import logging
import threading
from collections.abc import Callable

from patent_ai.core.runs.executor import RunExecutor
from patent_ai.core.runs.state import InvalidRunTransition, RunError, RunState
from patent_ai.core.runs.store import RunNotFound, RunStatusStore

logger = logging.getLogger(__name__)

# (run_id, oa_id)를 받아 실행을 시작시킨다
RunLauncher = Callable[[str, str], None]


class ThreadLauncher:
    def __init__(self, executor: RunExecutor, store: RunStatusStore) -> None:
        self._executor = executor
        self._store = store

    def __call__(self, run_id: str, oa_id: str) -> None:
        threading.Thread(
            target=self._run, args=(run_id, oa_id), name=f"run-{run_id}", daemon=True
        ).start()

    def _run(self, run_id: str, oa_id: str) -> None:
        try:
            self._executor.execute(run_id, oa_id)
        except Exception as exc:
            # 실행기가 예상 못 한 예외를 던져도 실행이 running으로 영영 남지 않게 failed로 남긴다
            logger.exception("실행 %s가 예외로 끝남", run_id)
            try:
                self._store.transition(
                    run_id,
                    RunState.FAILED,
                    error=RunError("executor_crashed", f"실행 중 오류: {exc}"),
                )
            except InvalidRunTransition, RunNotFound:
                logger.warning("실행 %s는 이미 끝나 있어 failed로 바꾸지 않는다", run_id)
