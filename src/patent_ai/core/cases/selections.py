"""사람 방향 선택 기록 저장·읽기 (이슈 #70). Postgres 구현은 `selections_pg.py`.

- `PUT /directions/{unit_id}/selection`이 사람이 고른 후보(human_selected)나 직접 쓴 방향
  (human_written)을 한 줄씩 쌓는다. 지우지 않는다 (사람 판단 이력).
- 줄마다 그 선택을 적용할 작은 실행(redo_drafts)의 run_id를 같이 둔다. 그 실행은 자기에게 묶인
  선택만 앞 F4 위에 덮는다 (앞 선택들은 이미 앞 F4의 selection에 들어 있다). 그래서 끝까지
  다시 돌린(full) 뒤에는 옛 선택이 새 후보 위에 되살아나지 않는다.
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
    def save_selection(
        self, oa_id: str, unit_id: str, selection: DirectionSelection, *, run_id: str
    ) -> None:
        """한 줄 더한다. run_id = 이 선택을 적용할 작은 실행. 사람 선택이 아니면 ValueError."""
        ...

    def selections_for_run(self, run_id: str) -> dict[str, DirectionSelection]:
        """그 작은 실행에 묶인 선택 (unit_id -> 선택). 없으면 빈 dict."""
        ...


class InMemorySelectionStore:
    """테스트용."""

    def __init__(self, clock: Callable[[], datetime] = now_utc) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._rows: list[tuple[str, str, str, datetime, DirectionSelection]] = []

    def save_selection(
        self, oa_id: str, unit_id: str, selection: DirectionSelection, *, run_id: str
    ) -> None:
        check_human(selection)
        with self._lock:
            self._rows.append((oa_id, run_id, unit_id, self._clock(), selection))

    def selections_for_run(self, run_id: str) -> dict[str, DirectionSelection]:
        with self._lock:
            return {unit_id: sel for _, rid, unit_id, _, sel in self._rows if rid == run_id}
