"""테스트 전용 가짜 저장소·결과 받는 곳·가짜 실행기. 앱 코드에서 import하지 않는다.

가짜 실행기는 앱의 공통 단계 루프(StepRunExecutor)를 그대로 쓴다.
그래서 취소·실패 처리는 앱 코드가 테스트된다.
"""

from pathlib import Path

from patent_ai.core.cases.store import InMemoryRunStore
from patent_ai.core.runs.cancel import CancelRegistry
from patent_ai.core.runs.executor import Skip, Step, StepRunExecutor, WaitForHuman
from patent_ai.core.runs.state import RunState
from patent_ai.core.runs.store import RunStatus
from patent_ai.core.schemas.oa_result import OAResult

FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "case_missing_citation" / "oa_result.json"
)


def load_oa_result() -> OAResult:
    return OAResult.model_validate_json(FIXTURE.read_text("utf-8"))


class MemoryStatusStore(InMemoryRunStore):
    """앱의 메모리 저장소(InMemoryRunStore)를 그대로 쓴다 (전이 규칙도 같은 코드).

    테스트 편의로 run_id를 정해 만드는 add()와 단계 기록 step_history만 더한다.
    """

    def __init__(self) -> None:
        super().__init__()
        self.step_history: dict[str, list[str]] = {}

    def add(
        self,
        run_id: str,
        oa_id: str = "oa_1",
        state: RunState = RunState.QUEUED,
        kind: str = "full",
    ) -> None:
        self._id_maker = lambda: run_id
        self.create_queued(oa_id, kind)
        if state != RunState.QUEUED:  # 규칙을 거치지 않고 바로 그 상태로 시작 (테스트 준비용)
            with self._lock:
                self._put(self._status[run_id].model_copy(update={"state": state}))
        self.step_history[run_id] = []

    @property
    def runs(self) -> dict[str, RunStatus]:
        return self._status

    def set_current_step(self, run_id: str, step: str) -> None:
        super().set_current_step(run_id, step)
        self.step_history[run_id].append(step)


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


def skipping_step(name: str, reason: str) -> Step:
    return Step(name, lambda: Skip(reason))
