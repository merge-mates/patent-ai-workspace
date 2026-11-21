"""oa_id 기준 OA 정리 저장·읽기의 Postgres 구현 (이슈 #57).

실행기가 백그라운드 스레드에서 부르므로 `PostgresRunStatusStore`처럼 세션 만드는 함수를 받아
호출마다 새 세션을 열고 커밋한다. 줄 만들기는 #16 `oa_result_row`를 다시 쓴다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from patent_ai.core.cases.results import SavedOAResult
from patent_ai.core.f1_oa_reader.case_repository import oa_result_row
from patent_ai.core.runs.state import RESULT_VISIBLE_STATES
from patent_ai.core.schemas.oa_result import OAResult
from patent_ai.db.models import OAResultRow, Run


class PostgresOAResultStore:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._factory = session_factory

    def save_oa_result(self, oa_id: str, run_id: str, result: OAResult) -> None:
        with self._factory() as s:
            s.add(OAResultRow(**asdict(oa_result_row(oa_id, run_id, result))))
            s.commit()

    def latest_visible_oa_result(self, oa_id: str) -> SavedOAResult | None:
        # runs와 이어 보여 줄 상태(succeeded·waiting_for_human)만.
        # 시각이 같으면 runs.created_at, 그다음 id 순
        q = (
            select(OAResultRow)
            .join(Run, OAResultRow.run_id == Run.id)
            .where(
                OAResultRow.oa_id == oa_id,
                Run.state.in_([st.value for st in RESULT_VISIBLE_STATES]),
            )
            .order_by(OAResultRow.created_at.desc(), Run.created_at.desc(), Run.id.desc())
            .limit(1)
        )
        with self._factory() as s:
            row = s.scalars(q).first()
            if row is None:
                return None
            return SavedOAResult(row.run_id, OAResult.model_validate(row.body))
