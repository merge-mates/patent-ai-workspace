"""단계 기록: 지휘가 도구를 부르거나 다음 일을 정할 때마다 한 줄. DB 구현은 #55 뒤."""

from typing import Literal, Protocol

from pydantic import BaseModel


class StepRecord(BaseModel):
    run_id: str
    step_kind: Literal["code_tool", "fixed_stage", "decide"]
    tool_name: str
    reason: str  # 왜 불렀나 ("지휘 선택" / "고정 단계" / "고정 순서" / 지휘 모델이 준 이유)
    result_status: str | None = None  # 결과 status 값. 실패하면 None
    model_call_count: int = 0  # 이 단계에서 모델을 부른 횟수
    outcome: Literal["ok", "failed", "waiting"]


class StepRecorder(Protocol):
    def record(self, step: StepRecord) -> None: ...


class MemoryStepRecorder:
    """메모리에 쌓는 기록기 (DB agent_steps 구현은 #55 뒤)."""

    def __init__(self) -> None:
        self.records: list[StepRecord] = []

    def record(self, step: StepRecord) -> None:
        self.records.append(step)
