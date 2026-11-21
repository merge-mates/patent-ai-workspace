"""단계 기록: 지휘가 도구를 부르거나 다음 일을 정할 때마다 한 줄. DB 구현은 #55 뒤."""

from typing import Literal, Protocol

from pydantic import BaseModel

# 넘긴 단계의 reason 칸 앞머리. outcome은 waiting, result_status는 unverified로 같이 적는다
SKIP_PREFIX = "넘김: "


class StepRecord(BaseModel):
    run_id: str
    step_kind: Literal["code_tool", "fixed_stage", "decide", "check"]
    tool_name: str
    # 왜 불렀나 ("지휘 선택" / "고정 단계" / "고정 순서" / 지휘 모델이 준 이유).
    # 돌리지 않고 넘긴 단계는 "넘김: <이유>" (SKIP_PREFIX)
    reason: str
    result_status: str | None = None  # 결과 status 값. 실패하면 None
    result_id: str | None = None  # 만든 결과 ID (DB가 생기는 #55 뒤에 채움)
    model_call_count: int | None = None  # 이 단계의 실제 전송 시도 수. 셀 수 없는 기록기면 None
    # ok = 돌았음 / failed = 실패 / waiting = 돌지 못하고 기다림 (사람 확인, 또는 넘긴 단계).
    # 넘긴 단계에 새 값을 두지 않는 이유: DB agent_steps.outcome 검사 제약이 이 세 값만 받는다
    outcome: Literal["ok", "failed", "waiting"]

    @property
    def skipped_reason(self) -> str | None:
        """단계를 돌리지 않고 넘겼으면 그 이유 ("tool_missing: …", "input_unverified: …").

        칸이 아니라 reason 칸에서 읽는다: 칸을 더하면 DB agent_steps 컬럼도 더해야 한다.
        이 값이 있으면 그 단계 결과는 없다 (성공이 아니다).
        """
        if self.outcome == "waiting" and self.reason.startswith(SKIP_PREFIX):
            return self.reason[len(SKIP_PREFIX) :]
        return None


class StepRecorder(Protocol):
    def record(self, step: StepRecord) -> None: ...


class MemoryStepRecorder:
    """메모리에 쌓는 기록기 (DB agent_steps 구현은 #55 뒤)."""

    def __init__(self) -> None:
        self.records: list[StepRecord] = []

    def record(self, step: StepRecord) -> None:
        self.records.append(step)
