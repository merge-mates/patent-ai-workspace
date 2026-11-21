"""실행기가 저장소에 바라는 것만 Protocol로 정의한다.

진짜 저장소(Postgres·InMemory RunStore)는 이 Protocol을 따르게 나중에 붙인다.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from patent_ai.core.runs.state import RunError, RunState
from patent_ai.core.schemas.oa_result import OAResult


class RunNotFound(LookupError):
    """없는 실행 id."""


class RunStatus(BaseModel):
    """실행 한 줄의 상태 (runs 표의 상태 칸들)."""

    run_id: str
    oa_id: str
    state: RunState
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
    ) -> RunStatus:
        """지금 상태를 읽어 check_transition으로 검사한 뒤 바꾼다. 안 되면 InvalidRunTransition."""
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
    """끝난 OA 정리를 받아 저장하는 쪽 (나중에 core/cases의 save_oa_result)."""

    def save_oa_result(self, oa_id: str, run_id: str, result: OAResult) -> None: ...
