"""실행기가 저장소에 바라는 것만 Protocol로 정의한다.

진짜 저장소(Postgres·InMemory RunStore)는 이 Protocol을 따른다.
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol, get_args

from pydantic import BaseModel

from patent_ai.core.runs.state import RunError, RunState
from patent_ai.core.schemas.oa_result import OAResult

# 실행 종류 (runs.kind, #70): 끝까지 도는 실행 / 사람이 방향을 고른 뒤 초안만 다시 만드는 작은 실행
RunKind = Literal["full", "redo_drafts"]
RUN_KINDS: frozenset[str] = frozenset(get_args(RunKind))


def check_run_kind(kind: str) -> None:
    """모르는 실행 종류면 ValueError (DB CHECK에 닿기 전에 막는다)."""
    if kind not in RUN_KINDS:
        raise ValueError(f"모르는 실행 종류: {kind!r} (가능: {sorted(RUN_KINDS)})")


class RunNotFound(LookupError):
    """없는 실행 id."""


class RunStatus(BaseModel):
    """실행 한 줄의 상태 (runs 표의 상태 칸들)."""

    run_id: str
    oa_id: str
    state: RunState
    kind: RunKind = "full"
    current_step: str | None = None
    waiting_for: str | None = None
    error: dict[str, Any] | None = None  # {code, message}


@dataclass(frozen=True)
class SkippedStep:
    """넘긴 단계 하나: 단계 이름과 넘긴 이유 (agent_steps의 outcome = 'skipped' 줄)."""

    step: str
    reason: str


class RunStatusStore(Protocol):
    def get_status(self, run_id: str) -> RunStatus | None:
        """없으면 None."""
        ...

    def transition(
        self,
        run_id: str,
        new: RunState,
        *,
        current_step: str | None = None,
        waiting_for: str | None = None,
        error: RunError | None = None,
        expected: RunState | None = None,
    ) -> RunStatus:
        """지금 상태를 읽어 check_transition으로 검사한 뒤 바꾼다. 안 되면 InvalidRunTransition.

        expected를 주면 지금 상태가 그것일 때만 바꾼다.
        """
        ...

    def set_current_step(self, run_id: str, step: str) -> None: ...

    def record_skipped(self, run_id: str, step: str, reason: str) -> None:
        """자료·도구가 없어 넘긴 단계를 남긴다. 실행 상태는 바꾸지 않는다."""
        ...

    def skipped_steps(self, run_id: str) -> list[SkippedStep]:
        """넘긴 단계를 기록한 순서로. 없으면 빈 목록."""
        ...

    def unfinished_run_ids(self) -> list[str]:
        """queued·running인 실행 id (켜질 때 failed로 바꿀 대상). waiting_for_human은 뺀다."""
        ...


class OAResultSink(Protocol):
    """끝난 OA 정리를 받아 저장하는 쪽. 실행기가 아는 것은 저장 한 가지뿐이다.

    core/cases/results.py의 OAResultStore가 이 약속을 잇고 읽기를 더한다 (실제 구현은 그쪽).
    """

    def save_oa_result(self, oa_id: str, run_id: str, result: OAResult) -> None: ...
