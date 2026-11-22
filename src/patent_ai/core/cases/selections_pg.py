"""사람 방향 선택 기록의 Postgres 구현 (이슈 #70). 표는 db/models/results.py DirectionSelectionRow.

API 요청 스레드와 실행기 스레드가 같이 부르므로 세션 만드는 함수를 받아 호출마다 새 세션을 연다.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from patent_ai.core.cases.selections import check_human
from patent_ai.core.schemas.common import Origin
from patent_ai.core.schemas.direction import DirectionSelection
from patent_ai.db.models import DirectionSelectionRow


class PostgresSelectionStore:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._factory = session_factory

    def save_selection(
        self, oa_id: str, unit_id: str, selection: DirectionSelection, *, run_id: str
    ) -> None:
        check_human(selection)
        with self._factory() as s:
            s.add(
                DirectionSelectionRow(
                    oa_id=oa_id,
                    run_id=run_id,
                    unit_id=unit_id,
                    candidate_id=selection.candidate_id,
                    written_direction=selection.written_direction,
                    origin=selection.origin.value,
                )
            )
            s.commit()

    def selections_for_run(self, run_id: str) -> dict[str, DirectionSelection]:
        q = (
            select(DirectionSelectionRow)
            .where(DirectionSelectionRow.run_id == run_id)
            .order_by(DirectionSelectionRow.created_at, DirectionSelectionRow.id)
        )
        out: dict[str, DirectionSelection] = {}
        with self._factory() as s:
            for r in s.scalars(q):
                out[r.unit_id] = DirectionSelection(
                    candidate_id=r.candidate_id,
                    written_direction=r.written_direction,
                    origin=Origin(r.origin),
                )
        return out
