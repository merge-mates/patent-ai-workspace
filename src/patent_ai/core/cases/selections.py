"""사람 방향 선택 기록 저장·읽기 (이슈 #70). Postgres 구현은 `selections_pg.py`.

- `PUT /directions/{unit_id}/selection`이 사람이 고른 후보(human_selected)나 직접 쓴 방향
  (human_written)을 한 줄씩 쌓는다. 지우지 않는다 (사람 판단 이력).
- 묶음(oa_id, unit_id)마다 가장 최근 줄이 지금 선택이다. 초안만 다시 만드는 작은 실행이 읽는다.
- AI 기본값(ai_default)은 여기 넣지 않는다: 이 기록은 사람 판단만 담아 AI 결과와 구분한다.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from patent_ai.core.cases.store import now_utc
from patent_ai.core.schemas.common import Origin
from patent_ai.core.schemas.direction import DirectionSelection

HUMAN_ORIGINS = frozenset({Origin.HUMAN_SELECTED, Origin.HUMAN_WRITTEN})


def check_human(selection: DirectionSelection) -> None:
    """사람 선택이 아니면 ValueError (AI 기본값을 사람 판단처럼 남기지 않는다)."""
    if selection.origin not in HUMAN_ORIGINS:
        raise ValueError(f"사람 선택만 기록한다 (origin={selection.origin.value})")


class SelectionStore(Protocol):
    def save_selection(self, oa_id: str, unit_id: str, selection: DirectionSelection) -> None:
        """한 줄 더한다. 사람 선택(human_selected·human_written)이 아니면 ValueError."""
        ...

    def latest_selections(self, oa_id: str) -> dict[str, DirectionSelection]:
        """그 OA에서 묶음(unit_id)마다 가장 최근 선택. 없으면 빈 dict."""
        ...


class InMemorySelectionStore:
    """테스트용. 시각이 같으면 나중에 넣은 줄이 이긴다 (Postgres는 id 순서로 같은 규칙)."""

    def __init__(self, clock: Callable[[], datetime] = now_utc) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._rows: list[tuple[str, str, datetime, int, DirectionSelection]] = []

    def save_selection(self, oa_id: str, unit_id: str, selection: DirectionSelection) -> None:
        check_human(selection)
        with self._lock:
            self._rows.append((oa_id, unit_id, self._clock(), len(self._rows), selection))

    def latest_selections(self, oa_id: str) -> dict[str, DirectionSelection]:
        with self._lock:
            mine = sorted((r for r in self._rows if r[0] == oa_id), key=lambda r: (r[2], r[3]))
        # 오래된 것부터 덮어써서 묶음마다 마지막 줄이 남는다
        return {unit_id: sel for _, unit_id, _, _, sel in mine}
