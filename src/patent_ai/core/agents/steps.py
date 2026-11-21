"""단계 기록: 지휘가 도구를 부르거나 다음 일을 정할 때마다 한 줄. DB 구현은 #55 뒤."""

from typing import Literal, Protocol

from pydantic import BaseModel


class StepRecord(BaseModel):
    run_id: str
    step_kind: Literal["code_tool", "fixed_stage", "decide", "check"]
    tool_name: str
    # 왜 불렀나 ("지휘 선택" / "고정 단계" / "고정 순서" / 지휘 모델이 준 이유).
    # 돌리지 않고 넘긴 단계(outcome skipped)는 넘긴 이유 ("tool_missing: …", "input_unverified: …")
    reason: str
    result_status: str | None = None  # 결과 status 값. 실패하면 None
    result_id: str | None = None  # 만든 결과 ID (DB가 생기는 #55 뒤에 채움)
    model_call_count: int | None = None  # 이 단계의 실제 전송 시도 수. 셀 수 없는 기록기면 None
    # ok = 돌았음 / failed = 실패 / waiting = 사람을 기다림 / skipped = 자료·도구가 없어 넘김.
    # DB agent_steps.outcome 검사 제약도 skipped를 받는다 (#187 마이그레이션)
    outcome: Literal["ok", "failed", "waiting", "skipped"]

    @property
    def skipped_reason(self) -> str | None:
        """넘긴 단계면 그 이유. 이 값이 있으면 그 단계 결과는 없다 (성공이 아니다)."""
        return self.reason if self.outcome == "skipped" else None


class StepRecorder(Protocol):
    def record(self, step: StepRecord) -> None: ...


class MemoryStepRecorder:
    """메모리에 쌓는 기록기 (DB agent_steps 구현은 #55 뒤)."""

    def __init__(self) -> None:
        self.records: list[StepRecord] = []

    def record(self, step: StepRecord) -> None:
        self.records.append(step)
