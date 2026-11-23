"""실행 상태 저장소의 Postgres 구현 (이슈 #57). 표는 db/models/runs.py, 규칙은 state.py.

실행은 서버 안 백그라운드 스레드에서 돈다. 그래서 #56처럼 세션 하나를 받지 않고
세션 만드는 함수(sessionmaker)를 받아, 메서드를 부를 때마다 새 세션을 열고 바로 커밋한다.
(커밋해야 화면의 폴링이 바뀐 상태를 바로 본다.)
표는 #55에서 만든 runs·agent_steps를 쓴다 (agent_steps.outcome의 skipped는 별도 마이그레이션).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from patent_ai.core.cases.store import now_utc
from patent_ai.core.runs.state import (
    FINISHED_STATES,
    UNFINISHED_STATES,
    RunError,
    RunState,
    check_transition,
)
from patent_ai.core.runs.store import RunNotFound, RunStatus, SkippedStep
from patent_ai.db.models import AgentStep, Run


def _status(r: Run) -> RunStatus:
    return RunStatus(
        run_id=r.id,
        oa_id=r.oa_id,
        state=RunState(r.state),
        kind=r.kind,
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
        expected: RunState | None = None,
    ) -> RunStatus:
        with self._factory() as s:
            # 줄을 잠그고 지금 DB 값을 읽는다. 끝나는 순간과 겹치면 먼저 쓴 쪽이 이기고,
            # 늦은 쪽은 잠금이 풀린 뒤 바뀐 값을 읽어 규칙에 막힌다.
            run = s.get(Run, run_id, with_for_update=True, populate_existing=True)
            if run is None:
                raise RunNotFound(run_id)
            check_transition(
                RunState(run.state), new, error=error, waiting_for=waiting_for, expected=expected
            )
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

    def record_skipped(self, run_id: str, step: str, reason: str) -> None:
        # 넘긴 단계 한 줄을 agent_steps에 적고 바로 커밋한다 (폴링하는 쪽이 보게)
        with self._factory() as s:
            if s.get(Run, run_id) is None:
                raise RunNotFound(run_id)
            s.add(
                AgentStep(
                    run_id=run_id,
                    step_kind="code_tool",
                    tool_name=step,
                    outcome="skipped",
                    reason=reason,
                )
            )
            s.commit()

    def skipped_steps(self, run_id: str) -> list[SkippedStep]:
        with self._factory() as s:
            q = (
                select(AgentStep)
                .where(
                    AgentStep.run_id == run_id,
                    or_(
                        AgentStep.outcome == "skipped",
                        # decide 줄의 limit_reached는 넘긴 단계가 아니다 (code_tool 줄만)
                        and_(
                            AgentStep.outcome == "limit_reached",
                            AgentStep.step_kind == "code_tool",
                        ),
                    ),
                )
                .order_by(AgentStep.id)  # id는 자동 증가라 기록 순서
            )
            return [SkippedStep(r.tool_name, r.reason or "") for r in s.scalars(q)]

    def unfinished_run_ids(self) -> list[str]:
        with self._factory() as s:
            q = (
                select(Run.id)
                .where(Run.state.in_([s.value for s in UNFINISHED_STATES]))
                .order_by(Run.created_at, Run.id)
            )
            return list(s.scalars(q))
