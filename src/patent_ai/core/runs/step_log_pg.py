"""지휘 단계 기록(StepRecord)을 agent_steps에 남기는 기록기 (이슈 #216 T1).

ok·failed·waiting·skipped 단계를 모두 쓴다. 실행이 끝난 뒤에도 어느 단계가 돌았는지 볼 수 있다.
PostgresRunStatusStore와 같이 호출마다 새 세션을 열고 바로 커밋한다 (폴링하는 쪽이 바로 보게).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from patent_ai.core.agents.steps import StepRecord
from patent_ai.core.llm.limits import CallRecord
from patent_ai.core.runs.store import RunLogWriteFailed
from patent_ai.db.models import AgentStep

logger = logging.getLogger(__name__)


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
                        unit_id=step.unit_id,
                        tool_input=step.tool_input,
                    )
                )
                s.commit()
        except SQLAlchemyError as e:
            # DB 예외를 실행기가 아는 예외로 바꾼다 (조용히 삼키지 않는다)
            raise RunLogWriteFailed(step.tool_name) from e

    def link_result(self, run_id: str, tool_name: str, result_id: str) -> None:
        """그 실행·도구의 마지막 ok 단계 줄에 step_results ID를 쓴다 (#267).

        단계 줄은 단계가 끝날 때(폴링하는 화면이 보게) 먼저 쓰이고, 결과는 실행 끝에 저장되므로
        나중에 붙인다. code_tool ok 줄만 고른다 (decide·model_call·skipped·failed 줄은 안 건드림).
        """
        q = (
            select(AgentStep)
            .where(
                AgentStep.run_id == run_id,
                AgentStep.tool_name == tool_name,
                # decide 줄(tool_name = 고른 도구)과 모델 호출 줄은 결과를 만들지 않는다
                AgentStep.step_kind == "code_tool",
                AgentStep.outcome == "ok",
            )
            .order_by(AgentStep.id.desc())
            .limit(1)
        )
        try:
            with self._factory() as s:
                row = s.scalars(q).first()
                if row is None:
                    # 조용히 지나가지 않게 남긴다 (결과는 저장됐는데 가리킬 단계 줄이 없다)
                    logger.warning("실행 %s: 결과 ID를 붙일 %s ok 기록이 없다", run_id, tool_name)
                    return
                row.result_id = result_id
                s.commit()
        except SQLAlchemyError as e:
            raise RunLogWriteFailed(tool_name) from e


class PostgresCallRecorder:
    """모델 호출 기록(CallRecord)을 agent_steps에 step_kind = model_call로 남긴다 (#216 T2).

    records는 이 실행의 호출을 메모리에도 쌓는다: 지휘(orchestrator)가 이것을 세어
    단계 기록의 model_call_count를 만든다. 없으면 그 칸이 None(확인 안 됨)이 된다.
    실행마다 새로 만들어야 records가 실행끼리 섞이지 않는다.
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._factory = session_factory
        self.records: list[CallRecord] = []

    def record(self, rec: CallRecord) -> None:
        try:
            with self._factory() as s:
                s.add(
                    AgentStep(
                        run_id=rec.run_id,
                        step_kind="model_call",
                        tool_name=rec.step,
                        outcome=rec.outcome,
                        model=rec.model,
                        input_tokens=rec.input_tokens,
                        output_tokens=rec.output_tokens,
                        # float 오차가 안 붙게 글자를 거쳐 Decimal로
                        cost=None if rec.cost is None else Decimal(str(rec.cost)),
                        elapsed_ms=rec.elapsed_ms,
                        from_cache=rec.from_cache,
                        attempt=rec.attempt,
                        transport_try=rec.transport_try,
                        stop_reason=rec.stop_reason,
                    )
                )
                s.commit()
        except SQLAlchemyError as e:
            # 쓰기 실패를 삼키지 않는다: 실행기가 record_failed로 실행을 실패 처리한다
            raise RunLogWriteFailed(rec.step) from e
        # DB에 남은 뒤에만 메모리에 붙인다 (센 값과 DB가 어긋나지 않게)
        self.records.append(rec)
