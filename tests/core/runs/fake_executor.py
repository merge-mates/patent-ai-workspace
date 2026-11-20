"""테스트 전용 가짜 저장소·결과 받는 곳·가짜 실행기. 앱 코드에서 import하지 않는다.

가짜 실행기는 앱의 공통 단계 루프(StepRunExecutor)를 그대로 쓴다.
그래서 취소·실패 처리는 앱 코드가 테스트된다.
"""

from pathlib import Path

from patent_ai.core.runs.cancel import CancelRegistry
from patent_ai.core.runs.executor import Step, StepRunExecutor, WaitForHuman
from patent_ai.core.runs.state import RunError, RunState, check_transition
from patent_ai.core.runs.store import RunStatus
from patent_ai.core.schemas.oa_result import OAResult

FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "case_missing_citation" / "oa_result.json"
)


def load_oa_result() -> OAResult:
    return OAResult.model_validate_json(FIXTURE.read_text("utf-8"))


class MemoryStatusStore:
    """RunStatusStore를 메모리로 흉내 낸다. transition은 check_transition을 꼭 거친다."""

    def __init__(self) -> None:
        self.runs: dict[str, RunStatus] = {}
        self.step_history: dict[str, list[str]] = {}

    def add(self, run_id: str, oa_id: str = "oa_1", state: RunState = RunState.QUEUED) -> None:
        self.runs[run_id] = RunStatus(run_id=run_id, oa_id=oa_id, state=state)
        self.step_history[run_id] = []

    def get_status(self, run_id: str) -> RunStatus | None:
        return self.runs.get(run_id)

    def transition(
        self,
        run_id: str,
        new: RunState,
        *,
        current_step: str | None = None,
        waiting_for: str | None = None,
        error: RunError | None = None,
    ) -> RunStatus:
        cur = self.runs[run_id]
        check_transition(cur.state, new, error=error, waiting_for=waiting_for)
        updated = cur.model_copy(
            update={
                "state": new,
                "current_step": current_step if current_step is not None else cur.current_step,
                "waiting_for": waiting_for,
                "error": error.to_dict() if error else None,
            }
        )
        self.runs[run_id] = updated
        return updated

    def set_current_step(self, run_id: str, step: str) -> None:
        self.runs[run_id] = self.runs[run_id].model_copy(update={"current_step": step})
        self.step_history[run_id].append(step)


class MemorySink:
    """OAResultSink를 메모리로 흉내 낸다."""

    def __init__(self) -> None:
        self.saved: list[tuple[str, str, OAResult]] = []

    def save_oa_result(self, oa_id: str, run_id: str, result: OAResult) -> None:
        self.saved.append((oa_id, run_id, result))


class FailingSink:
    def save_oa_result(self, oa_id: str, run_id: str, result: OAResult) -> None:
        raise RuntimeError("저장 실패")


def make_fake_executor(
    store: MemoryStatusStore,
    registry: CancelRegistry,
    sink,
    steps: list[Step] | None = None,
) -> StepRunExecutor:
    """기본 단계 두 개(OA 읽는 중, 거절이유 정리 중)로 성공하는 가짜 실행기."""
    return StepRunExecutor(
        store=store,
        registry=registry,
        sink=sink,
        steps=steps or [Step("OA 읽는 중", lambda: None), Step("거절이유 정리 중", lambda: None)],
        get_result=load_oa_result,
    )


def raising_step(name: str, exc: Exception) -> Step:
    def _run() -> None:
        raise exc

    return Step(name, _run)


def waiting_step(name: str, waiting_for: str) -> Step:
    return Step(name, lambda: WaitForHuman(waiting_for))


def cancelling_step(
    name: str, registry: CancelRegistry, run_id: str, log: list[str] | None = None
) -> Step:
    """이 단계가 도는 중에 취소 요청이 들어온 것처럼 흉내 낸다 (sleep 없이)."""

    def _run() -> None:
        if log is not None:
            log.append(name)
        registry.request(run_id)

    return Step(name, _run)


def recording_step(name: str, log: list[str]) -> Step:
    return Step(name, lambda: log.append(name))
