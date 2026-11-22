"""사람이 넣은 값 기록 (이슈 #70 계획 ②). Postgres 구현은 `human_inputs_pg.py`.

- 번호: 실행이 출원번호·발송번호를 못 읽어 사람을 기다릴 때 사람이 넣은 값. run_id는 그 번호로
  이어 돌 실행이다. 실행기는 이어 돌 때 이 실행의 번호만 읽는다.
- 확인("맞아요"): 사람이 보이는 OA 정리를 확인했다는 표시. run_id는 그 정리를 낸 실행이다.
지우지 않고 쌓는다. AI가 읽은 값과 사람 입력을 데이터에서 구분하려고 따로 둔다.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from typing import Literal, Protocol, get_args

from patent_ai.core.cases.store import now_utc

HumanInputKind = Literal["application_number", "dispatch_number", "oa_result_confirmed"]
NumberKind = Literal["application_number", "dispatch_number"]
HUMAN_INPUT_KINDS: frozenset[str] = frozenset(get_args(HumanInputKind))


class HumanInputStore(Protocol):
    def add(self, oa_id: str, run_id: str, kind: HumanInputKind, value: str | None) -> datetime:
        """한 줄 더하고 남긴 시각을 돌려준다. 번호는 value가 있어야, 확인은 value가 없어야 한다."""
        ...

    def numbers_for_run(self, run_id: str) -> dict[str, str]:
        """그 실행에 넣은 번호 (종류 -> 값, 종류마다 가장 최근). 없으면 빈 dict."""
        ...

    def confirmed_at(self, oa_id: str, run_id: str) -> datetime | None:
        """그 실행의 OA 정리를 사람이 확인한 가장 최근 시각. 확인 전이면 None."""
        ...


def check_row(kind: str, value: str | None) -> None:
    """모르는 종류, 번호인데 값 없음, 확인인데 값 있음이면 ValueError (DB CHECK에 닿기 전에)."""
    if kind not in HUMAN_INPUT_KINDS:
        raise ValueError(f"모르는 사람 입력 종류: {kind!r}")
    if kind == "oa_result_confirmed":
        if value is not None:
            raise ValueError("확인(oa_result_confirmed)은 값이 없다")
    elif value is None or not value.strip():
        raise ValueError(f"{kind}는 값이 있어야 한다")


class InMemoryHumanInputStore:
    """테스트용. 같은 시각이면 나중에 넣은 줄이 이긴다."""

    def __init__(self, clock: Callable[[], datetime] = now_utc) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._rows: list[tuple[str, str, str, str | None, datetime]] = []

    def add(self, oa_id: str, run_id: str, kind: HumanInputKind, value: str | None) -> datetime:
        check_row(kind, value)
        at = self._clock()
        with self._lock:
            self._rows.append((oa_id, run_id, kind, value, at))
        return at

    def numbers_for_run(self, run_id: str) -> dict[str, str]:
        with self._lock:
            rows = [r for r in self._rows if r[1] == run_id and r[2] != "oa_result_confirmed"]
        return {kind: value for _, _, kind, value, _ in rows if value is not None}

    def confirmed_at(self, oa_id: str, run_id: str) -> datetime | None:
        with self._lock:
            times = [
                at
                for oa, run, kind, _, at in self._rows
                if oa == oa_id and run == run_id and kind == "oa_result_confirmed"
            ]
        return max(times, default=None)
