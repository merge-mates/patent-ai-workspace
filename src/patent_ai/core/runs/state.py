"""실행 상태 바꾸기 규칙. 상태 전이 판단은 이 파일 한 곳에만 둔다.

상태 값은 DB `runs.state` CHECK 제약과 같은 글자다.
"""

from dataclasses import dataclass
from enum import StrEnum


class RunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_HUMAN = "waiting_for_human"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


# 끝난 실행은 더 바뀌지 않는다
FINISHED_STATES = frozenset({RunState.SUCCEEDED, RunState.FAILED, RunState.CANCELLED})
# 서버가 켜질 때 failed로 정리할 대상 (돌던 스레드가 사라진 상태).
# waiting_for_human은 스레드가 없어 뺀다
UNFINISHED_STATES = frozenset({RunState.QUEUED, RunState.RUNNING})
# 아직 진행 중인 상태 (같은 OA에 진행 중 실행이 있는지 볼 때 쓴다)
ACTIVE_STATES = frozenset({RunState.QUEUED, RunState.RUNNING, RunState.WAITING_FOR_HUMAN})

# 허용 전이 표. 여기 없는 이동은 전부 거부한다.
_ALLOWED: dict[RunState, frozenset[RunState]] = {
    RunState.QUEUED: frozenset({RunState.RUNNING, RunState.CANCELLED, RunState.FAILED}),
    RunState.RUNNING: frozenset(
        {RunState.SUCCEEDED, RunState.FAILED, RunState.WAITING_FOR_HUMAN, RunState.CANCELLED}
    ),
    RunState.WAITING_FOR_HUMAN: frozenset({RunState.RUNNING, RunState.CANCELLED, RunState.FAILED}),
    RunState.SUCCEEDED: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.CANCELLED: frozenset(),
}


@dataclass(frozen=True)
class RunError:
    """실패 이유. DB JSONB(`runs.error`)에는 to_dict() 결과를 넣는다."""

    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class InvalidRunTransition(ValueError):
    """허용되지 않는 상태 변경."""


def check_transition(
    current: RunState,
    new: RunState,
    *,
    error: RunError | None = None,
    waiting_for: str | None = None,
) -> None:
    """current -> new 가 되는지 확인한다. 안 되면 InvalidRunTransition."""
    if new not in _ALLOWED[current]:
        raise InvalidRunTransition(
            f"실행 상태를 {current.value}에서 {new.value}(으)로 바꿀 수 없다"
            + (": 이미 끝난 실행은 바뀌지 않는다" if current in FINISHED_STATES else "")
        )
    # 실패는 이유가 꼭 남아야 한다 (조용히 실패하지 않기)
    if new == RunState.FAILED and (
        error is None or not error.code.strip() or not error.message.strip()
    ):
        raise InvalidRunTransition("failed로 바꾸려면 비지 않은 error(code, message)가 필요하다")
    # 사람을 기다릴 때는 무엇을 기다리는지 남긴다
    if new == RunState.WAITING_FOR_HUMAN and not (waiting_for and waiting_for.strip()):
        raise InvalidRunTransition("waiting_for_human으로 바꾸려면 waiting_for가 필요하다")
