"""사람 입력 기록의 Postgres 구현 (이슈 #70). 표는 db/models/results.py HumanInputRow.

API 요청 스레드와 실행기 스레드가 같이 부르므로 호출마다 새 세션을 열고 바로 커밋한다.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from patent_ai.core.cases.human_inputs import HumanInputKind, check_row
from patent_ai.db.models import HumanInputRow


class PostgresHumanInputStore:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._factory = session_factory

    def add(self, oa_id: str, run_id: str, kind: HumanInputKind, value: str | None) -> datetime:
        check_row(kind, value)
        with self._factory() as s:
            row = HumanInputRow(oa_id=oa_id, run_id=run_id, kind=kind, value=value)
            s.add(row)
            s.commit()
            return row.created_at

    def numbers_for_run(self, run_id: str) -> dict[str, str]:
        q = (
            select(HumanInputRow)
            .where(HumanInputRow.run_id == run_id, HumanInputRow.kind != "oa_result_confirmed")
            .order_by(HumanInputRow.created_at, HumanInputRow.id)
        )
        with self._factory() as s:
            return {r.kind: r.value for r in s.scalars(q) if r.value is not None}

    def confirmed_at(self, oa_id: str, run_id: str) -> datetime | None:
        q = select(func.max(HumanInputRow.created_at)).where(
            HumanInputRow.oa_id == oa_id,
            HumanInputRow.run_id == run_id,
            HumanInputRow.kind == "oa_result_confirmed",
        )
        with self._factory() as s:
            return s.scalar(q)
