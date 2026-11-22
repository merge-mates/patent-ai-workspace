"""F2·F3·F4 결과 저장·읽기의 Postgres 구현 (이슈 #191 T2). 표는 db/models/results.py StepResultRow.

실행기가 백그라운드 스레드에서 부르므로 `PostgresOAResultStore`처럼 세션 만드는 함수를 받아
호출마다 새 세션을 열고 커밋한다.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from patent_ai.core.cases.step_results import (
    DuplicateStepResult,
    StepBody,
    StepKind,
    kind_of,
    parse_body,
)
from patent_ai.db.models import StepResultRow


class PostgresStepResultStore:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._factory = session_factory

    def save_step_result(self, oa_id: str, run_id: str, body: StepBody) -> None:
        kind = kind_of(body)
        with self._factory() as s:
            s.add(
                StepResultRow(
                    oa_id=oa_id,
                    run_id=run_id,
                    kind=kind,
                    body=body.model_dump(mode="json"),
                    status=body.status.value.value,
                )
            )
            try:
                s.commit()
            except IntegrityError as e:
                name = getattr(getattr(e.orig, "diag", None), "constraint_name", None)
                if name == "uq_step_results_run_kind":
                    raise DuplicateStepResult(f"{run_id}/{kind}") from e
                raise

    def step_result(self, run_id: str, kind: StepKind) -> StepBody | None:
        q = select(StepResultRow.body).where(
            StepResultRow.run_id == run_id, StepResultRow.kind == kind
        )
        with self._factory() as s:
            body = s.scalars(q).first()
        return parse_body(kind, body) if body is not None else None
