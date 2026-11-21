"""사건 자료·보류 목록(⑥ CaseMaterials) 읽기 (이슈 #57 T6).

사건마다 최신 한 줄(`case_materials`)을 읽는다. 쓰는 쪽(지휘 에이전트·자료 더하기)은
이번 이슈 밖이라 메모리 fake에만 테스트용 `put`이 있다.
Postgres 구현은 실행 스레드에서도 쓸 수 있게 호출마다 새 세션을 연다 (results_pg.py와 같은 방식).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import Session

from patent_ai.core.schemas.case_materials import CaseMaterials
from patent_ai.db.models import CaseMaterialsRow


@dataclass(frozen=True)
class SavedCaseMaterials:
    run_id: str | None  # 자료만 더하고 실행 없이 저장된 줄은 None
    result: CaseMaterials


class CaseMaterialsStore(Protocol):
    def latest_case_materials(self, case_id: str) -> SavedCaseMaterials | None:
        """그 사건의 최신 사건 자료. 아직 없으면 None."""
        ...


class InMemoryCaseMaterialsStore:
    """테스트용. put은 테스트가 결과를 미리 넣는 용도다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[str, SavedCaseMaterials] = {}

    def put(self, case_id: str, run_id: str | None, result: CaseMaterials) -> None:
        with self._lock:
            self._rows[case_id] = SavedCaseMaterials(run_id, result)  # 사건마다 최신 한 줄

    def latest_case_materials(self, case_id: str) -> SavedCaseMaterials | None:
        with self._lock:
            return self._rows.get(case_id)


class PostgresCaseMaterialsStore:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._factory = session_factory

    def latest_case_materials(self, case_id: str) -> SavedCaseMaterials | None:
        with self._factory() as s:
            row = s.get(CaseMaterialsRow, case_id)
            if row is None:
                return None
            return SavedCaseMaterials(row.run_id, CaseMaterials.model_validate(row.body))
