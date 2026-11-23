"""단계 기록: 지휘가 도구를 부르거나 다음 일을 정할 때마다 한 줄. DB 구현은 runs/step_log_pg.py."""

import logging
from typing import Literal, Protocol

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# 호출 상한 이유 글의 앞머리 (#241). 지휘가 붙이고 실행기·경고·빈 이유가 이것으로 알아본다
LIMIT_PREFIX = "limit_reached: "


class StepRecord(BaseModel):
    run_id: str
    step_kind: Literal["code_tool", "fixed_stage", "decide", "check"]
    tool_name: str
    # 왜 불렀나 ("지휘 선택" / "고정 단계" / "고정 순서" / 지휘 모델이 준 이유).
    # 돌리지 않고 넘긴 단계(outcome skipped)는 넘긴 이유 ("tool_missing: …", "input_unverified: …")
    reason: str
    result_status: str | None = None  # 결과 status 값. 실패하면 None
    # 일반 단계는 결과 저장 뒤 link_result로 step_results.id를 붙인다 (#267).
    # 다시 찾기 도구는 그때 돌려받은 조각 ID를 쉼표로 이어 남긴다.
    result_id: str | None = None
    model_call_count: int | None = None  # 이 단계의 실제 전송 시도 수. 셀 수 없는 기록기면 None
    # ok = 돌았음 / failed = 실패 / waiting = 사람을 기다림 / skipped = 자료·도구가 없어 넘김 /
    # limit_reached = 모델 호출 상한에 닿아 못 돎 (reason에 단계·상한 이름·숫자만, #241).
    # DB agent_steps.outcome 검사 제약도 두 값을 받는다 (#187·#241 마이그레이션)
    outcome: Literal["ok", "failed", "waiting", "skipped", "limit_reached"]
    # 다시 찾기 도구 줄(tool_name "recheck.<도구>")에서만 채운다. 옛 줄은 None.
    # tool_input은 길이를 제한한 도구 인자와 청구항·구성요소·인용문헌 식별 값을 담는다.
    unit_id: str | None = None
    tool_input: dict | None = None

    @property
    def skipped_reason(self) -> str | None:
        """넘긴 단계(skipped·limit_reached)면 그 이유. 이 값이 있으면 결과가 없다.

        skipped는 단계 종류를 안 가린다 (고정 단계도 넘길 수 있다. store_pg와 같은 규칙).
        limit_reached는 code_tool 줄만: decide 줄은 넘긴 단계가 아니다 (code_tool 줄이 따로 남는다).
        """
        if self.outcome == "skipped":
            return self.reason
        if self.outcome == "limit_reached" and self.step_kind == "code_tool":
            return self.reason
        return None


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
