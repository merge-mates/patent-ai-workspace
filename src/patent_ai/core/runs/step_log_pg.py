"""지휘 단계 기록(StepRecord)을 agent_steps에 남기는 기록기 (이슈 #216 T1).

ok·failed·waiting·skipped 단계를 모두 쓴다. 실행이 끝난 뒤에도 어느 단계가 돌았는지 볼 수 있다.
PostgresRunStatusStore와 같이 호출마다 새 세션을 열고 바로 커밋한다 (폴링하는 쪽이 바로 보게).
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from patent_ai.core.agents.steps import StepRecord
from patent_ai.core.runs.store import RunLogWriteFailed
from patent_ai.db.models import AgentStep


class PostgresStepRecorder:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._factory = session_factory

    def record(self, step: StepRecord) -> None:
        try:
            with self._factory() as s:
                s.add(
                    AgentStep(
                        run_id=step.run_id,
                        step_kind=step.step_kind,
                        tool_name=step.tool_name,
                        outcome=step.outcome,
                        reason=step.reason,
                        result_status=step.result_status,
                        result_id=step.result_id,
                        model_call_count=step.model_call_count,
                    )
                )
                s.commit()
        except SQLAlchemyError as e:
            # DB 예외를 실행기가 아는 예외로 바꾼다 (조용히 삼키지 않는다)
            raise RunLogWriteFailed(f"{step.tool_name} 단계 기록 저장 실패") from e
