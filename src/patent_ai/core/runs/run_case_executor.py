"""지휘 에이전트(run_case)를 부르는 실행기 (이슈 #191 T1). 앱 기본 실행기다.

실행 하나 = run_case 한 번. RunOutcome을 실행 상태로 옮긴다:
- succeeded / waiting_for_human: 결과(F1 OA 정리, F3, F4)를 먼저 저장하고 상태를 바꾼다.
  F1 뒤에는 읽은 번호를 사건에 넣고 사건 자료(⑥)를 만든다 (case_fill, #261)
  (상태부터 바꾸면 화면이 "끝남"을 보고 결과를 읽을 때 404가 난다).
- failed: 결과를 저장하지 않고 이유를 남긴다. 예외 원문은 로그에만 (safe_message).
- 단계 기록: 지휘가 단계 기록을 남길 때마다 바로 step_log 한 곳에 넘긴다 (서버는 agent_steps에
  ok·failed·waiting·skipped 모두, #216). 넘긴 단계도 거기 남아 폴링하는 화면이 도는 중에도 본다.
  step_log를 안 주면 넘긴 단계만 record_skipped로 옮긴다 (메모리 저장소 테스트용).
- 취소: 단계 기록이 하나 남을 때마다 취소 표시를 보고, 있으면 그 자리에서 멈춘다
  (지금 단계는 끝까지 돈 뒤라 "지금 단계가 끝난 뒤 cancelled" 규칙과 같다). 결과는 저장하지 않는다.
- 한 번에 하나: 서버 안 실행은 잠금 하나를 같이 쓴다. 뒤에 온 실행은 queued로 기다린다
  (모델 호출 상한·비용과 공유 DB 쓰기를 한 실행씩 보려고. 한 사람이 쓰는 앱이라 충분하다).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import date
from pathlib import Path

from patent_ai.core.agents.orchestrator import CaseStore, RunOutcome, run_case
from patent_ai.core.agents.steps import StepRecord, StepRecorder
from patent_ai.core.cases.case_fill import CaseFillSink
from patent_ai.core.cases.run_inputs import RunInputSource
from patent_ai.core.cases.step_results import StepResultStore
from patent_ai.core.llm.limits import RunContext
from patent_ai.core.runs.cancel import CancelRegistry
from patent_ai.core.runs.executor import safe_message
from patent_ai.core.runs.state import InvalidRunTransition, RunError, RunState
from patent_ai.core.runs.store import OAResultSink, RunLogWriteFailed, RunStatusStore
from patent_ai.core.schemas.document import PageText
from patent_ai.core.schemas.oa_result import OAResult

logger = logging.getLogger(__name__)

# 단계가 끝난 뒤 화면에 보일 "지금 하는 주요 작업" (다음에 도는 일)
_NEXT_STEP = {
    "extract_pages": "OA 정리 중",
    "read_oa": "OA 시점까지 자료 자르는 중",
    "cut_to_oa": "청구항–인용문헌 대비 중",
    "run_f3": "법률 근거 조사 중",
    "run_f2": "대응 방향·초안 만드는 중",
    "run_f4": "결과 저장 중",
}
FIRST_STEP = "OA 글자 읽는 중"

# 지휘가 낸 실패 코드 중 그대로 내보내는 것과 그 이유 글 (원문 예외 글은 쓰지 않는다)
_OUTCOME_MESSAGES = {
    "oa_already_exists": "이미 올린 OA입니다",
    "max_steps": "도구 호출 최대 횟수에 닿아 멈췄습니다",
    "invalid_tool_choice": "지휘 설정·선택이 잘못돼 멈췄습니다",
    "no_oa_result": "OA 정리 없이 멈췄습니다",
}


class _Cancelled(Exception):
    """단계 사이에서 취소 표시를 봤다 (run_case 밖으로 빠져나오려고 쓴다)."""


class _SkippedOnlySink:
    """step_log를 안 받았을 때 기본 기록 자리: 넘긴 단계만 실행 상태 저장소에 남긴다 (옛 동작)."""

    def __init__(self, store: RunStatusStore) -> None:
        self._store = store

    def record(self, step: StepRecord) -> None:
        if step.skipped_reason is not None:
            self._store.record_skipped(step.run_id, step.tool_name, step.skipped_reason)


class _LiveSteps:
    """지휘의 단계 기록기. 기록마다 sink 한 곳에 넘기고, 실행 상태를 옮기고, 취소 표시를 본다."""

    def __init__(
        self,
        run_id: str,
        store: RunStatusStore,
        registry: CancelRegistry,
        sink: StepRecorder,
    ) -> None:
        self._run_id = run_id
        self._store = store
        self._registry = registry
        self._sink = sink  # 기록을 쓰는 곳은 이 하나뿐 (같은 단계가 두 줄 남지 않게)
        self.records: list[StepRecord] = []

    def record(self, step: StepRecord) -> None:
        # 쓰기가 실패해도 어느 단계였는지 알 수 있게 목록에는 먼저 붙인다
        self.records.append(step)
        self._sink.record(step)
        nxt = _NEXT_STEP.get(step.tool_name)
        if nxt and step.outcome in ("ok", "skipped"):
            self._store.set_current_step(self._run_id, nxt)
        if self._registry.is_requested(self._run_id):
            raise _Cancelled


class RunCaseExecutor:
    def __init__(
        self,
        *,
        store: RunStatusStore,
        registry: CancelRegistry,
        oa_results: OAResultSink,
        step_results: StepResultStore,
        case_fill: CaseFillSink,
        inputs: RunInputSource,
        cases: CaseStore,
        config_path: Path,
        make_ctx: Callable[[str], RunContext],
        today: Callable[[], date],
        lock: threading.Lock | None = None,
        step_log: StepRecorder | None = None,
    ) -> None:
        self._store = store
        self._step_log = step_log or _SkippedOnlySink(store)
        self._registry = registry  # 취소 API와 같은 것이어야 취소가 닿는다
        self._oa_results = oa_results
        self._step_results = step_results
        self._case_fill = case_fill  # F1 뒤 사건 번호·사건 자료 (#261)
        self._inputs = inputs
        self._cases = cases
        self._config_path = config_path
        self._make_ctx = make_ctx  # 실행마다 새 모델 호출 맥락 (상한·기록이 실행끼리 안 섞이게)
        self._today = today  # F4 확인 기준일 = 실행한 날 (코드가 몰래 오늘을 읽지 않게 받는다)
        self._lock = lock or threading.Lock()

    def execute(self, run_id: str, oa_id: str) -> None:
        with self._lock:  # 한 번에 하나만 돈다
            try:
                self._run(run_id, oa_id)
            finally:
                self._registry.forget(run_id)

    def _finish(self, run_id: str, new: RunState, **kwargs) -> None:
        try:
            self._store.transition(run_id, new, **kwargs)
        except InvalidRunTransition:
            logger.warning("실행 %s는 이미 끝나 있어 %s로 바꾸지 않는다", run_id, new.value)

    def _fail(self, run_id: str, code: str, message: str) -> None:
        self._finish(run_id, RunState.FAILED, error=RunError(code, message))

    def _run(self, run_id: str, oa_id: str) -> None:
        # 기다리는 동안 취소됐으면(queued -> cancelled) 여기서 막혀 돌지 않는다
        try:
            self._store.transition(run_id, RunState.RUNNING, current_step=FIRST_STEP)
        except InvalidRunTransition:
            logger.warning("실행 %s를 시작할 수 없다 (이미 끝났거나 도는 중), 건너뛴다", run_id)
            return
        if self._registry.is_requested(run_id):
            self._finish(run_id, RunState.CANCELLED)
            return
        try:
            case_input = self._inputs.case_input(oa_id).model_copy(
                update={"checked_on": self._today()}
            )
        except Exception as exc:
            logger.exception("실행 %s의 입력을 만들지 못함", run_id)
            self._fail(run_id, "step_failed", safe_message("실행 입력 준비", exc))
            return

        steps = _LiveSteps(run_id, self._store, self._registry, self._step_log)
        try:
            outcome = run_case(
                case_input,
                oa_id,
                run_id,
                self._cases,
                self._config_path,
                ctx=self._make_ctx(run_id),
                steps=steps,
            )
        except _Cancelled:
            self._finish(run_id, RunState.CANCELLED)
            return
        except RunLogWriteFailed as e:
            # 기록을 못 남기면 성공으로 끝내지 않는다. 원문은 로그에만 (message에 안 넣음).
            # 어느 기록이었는지는 예외가 들고 온 이름을 쓴다 (모델 호출 실패는 단계 기록보다 먼저라
            # steps.records 끝을 보면 바로 앞 단계 이름이 찍힌다)
            logger.exception("실행 %s의 실행 기록 저장 실패", run_id)
            self._fail(run_id, "record_failed", f"실행 기록 저장 실패 ({e.where})")
            return
        except Exception as exc:  # run_case가 목록 밖 예외(버그·검색 자원 실패)를 올려 보냄
            logger.exception("실행 %s의 지휘가 예외로 끝남", run_id)
            where = steps.records[-1].tool_name if steps.records else "지휘"
            self._fail(run_id, "step_failed", safe_message(where, exc))
            return
        self._apply(run_id, oa_id, outcome, steps)

    def _apply(self, run_id: str, oa_id: str, outcome: RunOutcome, steps: _LiveSteps) -> None:
        if outcome.state == "failed":
            self._fail(run_id, *_outcome_error(outcome, steps))
            return
        # 끝난 뒤에도 한 번 더 본다 (취소면 결과를 저장하지 않는다)
        if self._registry.is_requested(run_id):
            self._finish(run_id, RunState.CANCELLED)
            return
        try:
            self._save(run_id, oa_id, outcome)
        except Exception as exc:
            logger.exception("실행 %s의 결과 저장 실패", run_id)
            self._fail(run_id, "result_save_failed", safe_message("결과 저장", exc))
            return
        if outcome.state == "waiting_for_human":
            self._finish(run_id, RunState.WAITING_FOR_HUMAN, waiting_for=outcome.waiting_for.value)
        else:
            self._finish(run_id, RunState.SUCCEEDED)

    def _save(self, run_id: str, oa_id: str, outcome: RunOutcome) -> None:
        """도구 이름 -> 결과 객체를 저장소별로 나눠 저장한다. 넘긴 단계는 결과가 없어 안 쓴다."""
        oa = outcome.results.get("read_oa")
        if not isinstance(oa, OAResult):
            # 성공·사람 기다림인데 OA 정리가 없으면 화면이 열 결과가 없다: 성공으로 두지 않는다
            raise ValueError("read_oa 결과 없음")
        self._oa_results.save_oa_result(oa_id, run_id, oa)
        # 읽은 출원번호·발송번호를 사건에 넣고 사건 자료(⑥)를 만든다 (#261)
        pages = outcome.results.get("extract_pages")
        text_status = pages.status if isinstance(pages, PageText) else None
        self._case_fill.fill_after_f1(oa_id, run_id, oa, text_status)
        for name in ("run_f3", "run_f2", "run_f4"):
            if name in outcome.results:
                self._step_results.save_step_result(oa_id, run_id, outcome.results[name])


def _outcome_error(outcome: RunOutcome, steps: _LiveSteps) -> tuple[str, str]:
    """지휘 실패를 (code, message)로. 메시지는 코드 표에서 만들고 예외 원문을 쓰지 않는다."""
    err = outcome.error or {}
    code = str(err.get("code") or "")
    if code in _OUTCOME_MESSAGES:
        message = _OUTCOME_MESSAGES[code]
        if code == "oa_already_exists" and err.get("oa_id"):
            message = f"{message} (OA {err['oa_id']})"
        return code, message
    # 도구 실패: 어느 단계에서 어떤 종류로 실패했는지만 (ModelOutputInvalid 등)
    failed = [r.tool_name for r in steps.records if r.outcome == "failed"]
    where = failed[-1] if failed else "지휘"
    return "step_failed", f"{where}: 실패 ({code or '알 수 없음'})"
