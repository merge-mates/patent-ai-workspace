"""단계 기록: 지휘가 도구를 부르거나 다음 일을 정할 때마다 한 줄. DB 구현은 runs/step_log_pg.py."""

import logging
from typing import Literal, Protocol

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class StepRecord(BaseModel):
    run_id: str
    step_kind: Literal["code_tool", "fixed_stage", "decide", "check"]
    tool_name: str
    # 왜 불렀나 ("지휘 선택" / "고정 단계" / "고정 순서" / 지휘 모델이 준 이유).
    # 돌리지 않고 넘긴 단계(outcome skipped)는 넘긴 이유 ("tool_missing: …", "input_unverified: …")
    reason: str
    result_status: str | None = None  # 결과 status 값. 실패하면 None
    # 만든 결과 ID (step_results.id). 기록은 단계가 끝날 때 먼저 남고, 실행기가 결과를 저장한 뒤
    # link_result로 붙인다 (#267). 결과를 안 만든 단계(skipped·failed)와 read_oa는 None
    result_id: str | None = None
    model_call_count: int | None = None  # 이 단계의 실제 전송 시도 수. 셀 수 없는 기록기면 None
    # ok = 돌았음 / failed = 실패 / waiting = 사람을 기다림 / skipped = 자료·도구가 없어 넘김 /
    # limit_reached = 모델 호출 상한에 닿아 못 돎 (reason에 단계·상한 이름·숫자만, #241).
    # DB agent_steps.outcome 검사 제약도 두 값을 받는다 (#187·#241 마이그레이션)
    outcome: Literal["ok", "failed", "waiting", "skipped", "limit_reached"]

    @property
    def skipped_reason(self) -> str | None:
        """넘긴 단계(skipped·limit_reached)면 그 이유. 이 값이 있으면 그 단계 결과는 없다."""
        return self.reason if self.outcome in ("skipped", "limit_reached") else None


class StepRecorder(Protocol):
    """run_case가 부르는 기록 자리. 단계마다 record만 부른다."""

    def record(self, step: StepRecord) -> None: ...


class StepLog(StepRecorder, Protocol):
    """서버 실행기(RunCaseExecutor)의 step_log 자리. 결과를 저장한 뒤 결과 ID를 붙인다 (#267)."""

    def link_result(self, run_id: str, tool_name: str, result_id: str) -> None:
        """그 실행·도구의 마지막 ok code_tool 기록에 결과 ID를 붙인다.

        단계 줄을 남기는 기록기는 붙일 줄이 없으면 경고를 남긴다.
        """
        ...


class MemoryStepRecorder:
    """메모리에 쌓는 기록기 (DB agent_steps 구현은 `core/runs/step_log_pg.py`)."""

    def __init__(self) -> None:
        self.records: list[StepRecord] = []

    def record(self, step: StepRecord) -> None:
        self.records.append(step)

    def link_result(self, run_id: str, tool_name: str, result_id: str) -> None:
        # 뒤에서부터 찾는다: 같은 도구를 다시 불렀으면 마지막으로 성공한 기록이 그 결과를 냈다
        for i in range(len(self.records) - 1, -1, -1):
            r = self.records[i]
            if (
                r.run_id == run_id
                and r.tool_name == tool_name
                and r.step_kind == "code_tool"
                and r.outcome == "ok"
            ):
                self.records[i] = r.model_copy(update={"result_id": result_id})
                return
        logger.warning("실행 %s: 결과 ID를 붙일 %s ok 기록이 없다", run_id, tool_name)
