"""oa_id 기준 OA 정리 결과 저장·읽기 (이슈 #57).

#16 `case_repository`의 번호(출원번호·발송번호) 기준 save/load와는 따로 둔다.
실행기(백그라운드 스레드)가 oa_id·run_id로 쓰고, API가 oa_id로 최근 성공 결과를 읽는다.
Postgres 구현은 `results_pg.py`.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from patent_ai.core.cases.store import InMemoryRunStore, now_utc
from patent_ai.core.runs.state import RESULT_VISIBLE_STATES
from patent_ai.core.runs.store import OAResultSink
from patent_ai.core.schemas.oa_result import OAResult


@dataclass(frozen=True)
class SavedOAResult:
    run_id: str
    result: OAResult


class OAResultStore(OAResultSink, Protocol):
    """저장(save_oa_result)은 OAResultSink에서 이어받고, 읽기를 더한다."""

    def latest_visible_oa_result(self, oa_id: str) -> SavedOAResult | None:
        """그 OA에서 보여 줄 실행(succeeded·waiting_for_human)이 낸 가장 최근 결과. 없으면 None.

        저장 시각이 같으면 실행을 만든 시각, 그래도 같으면 run id가 큰 쪽.
        """
        ...


class InMemoryOAResultStore:
    """테스트용. 실행 상태는 같은 InMemoryRunStore를 보고 보여 줄 상태만 고른다."""

    def __init__(self, runs: InMemoryRunStore, clock: Callable[[], datetime] = now_utc) -> None:
        self._runs = runs
        self._clock = clock
        self._lock = threading.Lock()
        self._saved: list[tuple[datetime, str, str, OAResult]] = []  # (저장 시각, oa, run, 결과)

    def save_oa_result(self, oa_id: str, run_id: str, result: OAResult) -> None:
        with self._lock:
            self._saved.append((self._clock(), oa_id, run_id, result))

    @property
    def saved(self) -> list[tuple[str, str, OAResult]]:
        """저장된 (oa_id, run_id, 결과) 전부. 상태와 상관없이 저장 호출 기록을 본다 (테스트용)."""
        with self._lock:
            return [(oa, run, res) for _, oa, run, res in self._saved]

    def latest_visible_oa_result(self, oa_id: str) -> SavedOAResult | None:
        best = None
        best_key = None
        for saved_at, saved_oa, run_id, result in self._saved:
            status = self._runs.get_status(run_id)
            row = self._runs.get_row(run_id)
            if saved_oa != oa_id or status is None or row is None:
                continue
            if status.state not in RESULT_VISIBLE_STATES:
                continue
            key = (saved_at, row.created_at, run_id)
            if best_key is None or key > best_key:
                best, best_key = SavedOAResult(run_id, result), key
        return best
