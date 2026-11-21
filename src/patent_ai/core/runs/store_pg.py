"""실행 상태 저장소의 Postgres 구현 (이슈 #57). 표는 db/models/runs.py, 규칙은 state.py.

실행은 서버 안 백그라운드 스레드에서 돈다. 그래서 #56처럼 세션 하나를 받지 않고
세션 만드는 함수(sessionmaker)를 받아, 메서드를 부를 때마다 새 세션을 열고 바로 커밋한다.
(커밋해야 화면의 폴링이 바뀐 상태를 바로 본다.)
마이그레이션 없음: #55에서 만든 표를 그대로 쓴다.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from patent_ai.core.cases.store import now_utc
from patent_ai.core.runs.state import FINISHED_STATES, RunError, RunState, check_transition
from patent_ai.core.runs.store import RunNotFound, RunStatus
from patent_ai.db.models import Run


def _status(r: Run) -> RunStatus:
    return RunStatus(
        run_id=r.id,
        oa_id=r.oa_id,
        state=RunState(r.state),
        current_step=r.current_step,
        waiting_for=r.waiting_for,
        error=r.error,
    )


class PostgresRunStatusStore:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        clock: Callable[[], datetime] = now_utc,
    ) -> None:
        self._factory = session_factory
        self._clock = clock

    def get_status(self, run_id: str) -> RunStatus | None:
        with self._factory() as s:
            run = s.get(Run, run_id)
            return _status(run) if run else None

    def transition(
        self,
        run_id: str,
        new: RunState,
        *,
        current_step: str | None = None,
        waiting_for: str | None = None,
        error: RunError | None = None,
    ) -> RunStatus:
        with self._factory() as s:
            # 줄을 잠그고 지금 DB 값을 읽는다. 끝나는 순간과 겹치면 먼저 쓴 쪽이 이기고,
            # 늦은 쪽은 잠금이 풀린 뒤 바뀐 값을 읽어 규칙에 막힌다.
            run = s.get(Run, run_id, with_for_update=True, populate_existing=True)
            if run is None:
                raise RunNotFound(run_id)
            check_transition(RunState(run.state), new, error=error, waiting_for=waiting_for)
            now = self._clock()
            run.state = new.value
            if current_step is not None:
                run.current_step = current_step
            run.waiting_for = waiting_for
            run.error = error.to_dict() if error else None
            if new == RunState.RUNNING and run.started_at is None:
                run.started_at = now
            if new in FINISHED_STATES:
                run.finished_at = now
            s.commit()
            return _status(run)

    def set_current_step(self, run_id: str, step: str) -> None:
        with self._factory() as s:
            run = s.get(Run, run_id, with_for_update=True, populate_existing=True)
            if run is None:
                raise RunNotFound(run_id)
            run.current_step = step
            s.commit()

    def unfinished_run_ids(self) -> list[str]:
        with self._factory() as s:
            q = (
                select(Run.id)
                .where(Run.state.in_([RunState.QUEUED.value, RunState.RUNNING.value]))
                .order_by(Run.created_at, Run.id)
            )
            return list(s.scalars(q))
