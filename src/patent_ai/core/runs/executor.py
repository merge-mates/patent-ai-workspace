"""실행기. 단계를 차례로 도는 공통 루프(StepRunExecutor)는 가짜 실행기도 쓴다.

실패는 failed + 이유로 남기고 성공으로 끝내지 않는다. 지휘 에이전트(run_case) 연결은 이 파일 밖.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from patent_ai.core.runs.cancel import CancelRegistry
from patent_ai.core.runs.state import InvalidRunTransition, RunError, RunState
from patent_ai.core.runs.store import OAResultSink, RunStatusStore
from patent_ai.core.schemas.oa_result import OAResult

logger = logging.getLogger(__name__)


class RunExecutor(Protocol):
    def execute(self, run_id: str, oa_id: str) -> None:
        """실행 하나를 끝까지(또는 사람 기다림·취소까지) 돌린다. 결과는 저장소에 남긴다."""
        ...


@dataclass(frozen=True)
class WaitForHuman:
    """단계가 돌려주면 실행이 waiting_for_human으로 멈춘다."""

    waiting_for: str


@dataclass(frozen=True)
class Skip:
    """단계가 돌려주면 그 단계를 skipped로 적고 다음 단계로 간다 (자료·도구 없음)."""

    reason: str


@dataclass(frozen=True)
class Step:
    name: str  # current_step에 보이는 한 줄
    run: Callable[[], WaitForHuman | Skip | None]


class NotConnectedExecutor:
    """앱 기본 실행기: 지휘 에이전트가 아직 안 붙었으니 바로 failed로 끝낸다."""

    def __init__(self, store: RunStatusStore) -> None:
        self._store = store

    def execute(self, run_id: str, oa_id: str) -> None:
        error = RunError("executor_not_connected", "지휘 에이전트 연결 전")
        try:
            self._store.transition(run_id, RunState.FAILED, error=error)
        except InvalidRunTransition:
            logger.warning("실행 %s는 이미 끝나 있어 failed로 바꾸지 않는다", run_id)


class StepRunExecutor:
    def __init__(
        self,
        *,
        store: RunStatusStore,
        registry: CancelRegistry,
        sink: OAResultSink,
        steps: list[Step],
        get_result: Callable[[], OAResult],
    ) -> None:
        self._store = store
        self._registry = registry
        self._sink = sink
        self._steps = steps
        self._get_result = get_result  # 마지막 단계 뒤에 OA 정리를 꺼내는 함수

    def execute(self, run_id: str, oa_id: str) -> None:
        try:
            self._run(run_id, oa_id)
        finally:
            self._registry.forget(run_id)

    def _finish(self, run_id: str, new: RunState, **kwargs) -> None:
        """끝 상태를 쓴다. 이미 끝난 실행이면(먼저 쓴 쪽이 이김) 로그만 남긴다."""
        try:
            self._store.transition(run_id, new, **kwargs)
        except InvalidRunTransition:
            logger.warning("실행 %s는 이미 끝나 있어 %s로 바꾸지 않는다", run_id, new.value)

    def _run(self, run_id: str, oa_id: str) -> None:
        # 시작: queued -> running. queued 때 취소돼 있으면 여기서 끝낸다
        try:
            self._store.transition(run_id, RunState.RUNNING)
        except InvalidRunTransition:
            logger.warning("실행 %s를 시작할 수 없다 (이미 끝났거나 도는 중), 건너뛴다", run_id)
            return

        for step in self._steps:
            # 단계 시작 전에 취소 표시를 본다
            if self._registry.is_requested(run_id):
                self._finish(run_id, RunState.CANCELLED)
                return
            self._store.set_current_step(run_id, step.name)
            try:
                outcome = step.run()
            except Exception as exc:  # 예외를 삼키지 않고 기록한 뒤 failed로 남긴다
                logger.exception("실행 %s의 단계 '%s' 실패", run_id, step.name)
                error = RunError("step_failed", f"{step.name}: {exc}")
                self._finish(run_id, RunState.FAILED, error=error)
                return
            if isinstance(outcome, WaitForHuman):
                self._finish(run_id, RunState.WAITING_FOR_HUMAN, waiting_for=outcome.waiting_for)
                return
            if isinstance(outcome, Skip):
                # 넘긴 단계는 이유와 함께 남기고 계속 간다. 나머지가 성공하면 succeeded
                logger.warning(
                    "실행 %s의 단계 '%s'를 건너뜀: %s", run_id, step.name, outcome.reason
                )
                self._store.record_skipped(run_id, step.name, outcome.reason)

        # 마지막 단계 뒤에도 한 번 더 본다 (취소면 결과를 저장하지 않는다)
        if self._registry.is_requested(run_id):
            self._finish(run_id, RunState.CANCELLED)
            return
        try:
            self._sink.save_oa_result(oa_id, run_id, self._get_result())
        except Exception as exc:
            logger.exception("실행 %s의 결과 저장 실패", run_id)
            self._finish(
                run_id,
                RunState.FAILED,
                error=RunError("result_save_failed", f"결과 저장 실패: {exc}"),
            )
            return
        self._finish(run_id, RunState.SUCCEEDED)
