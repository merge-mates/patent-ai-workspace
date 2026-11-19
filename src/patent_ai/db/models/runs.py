"""실행 기록 표: runs, agent_steps, api_cache (이슈 #55 task 2, docs/data-model.md 5절).

모델·토큰·비용 같은 실행 정보는 결과가 아니라 여기에 둔다.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from patent_ai.db.base import Base
from patent_ai.db.ids import id_factory


class Run(Base):
    """실행 하나 (API 실행 상태 겸). 실패를 succeeded로 두지 않는다."""

    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(
            "state IN ('queued', 'running', 'waiting_for_human', 'succeeded', 'failed', "
            "'cancelled')",
            name="ck_runs_state",
        ),
        Index("ix_runs_oa_id_created_at", "oa_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=id_factory("r"))
    oa_id: Mapped[str] = mapped_column(ForeignKey("oas.id"))
    state: Mapped[str] = mapped_column(Text, server_default="queued")
    current_step: Mapped[str | None] = mapped_column(Text)  # "지금 하는 주요 작업" 한 줄
    waiting_for: Mapped[str | None] = mapped_column(Text)  # waiting_for_human일 때 이유
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # {code, message}
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentStep(Base):
    """실행 안의 단계 한 줄: 지휘 단계(StepRecord)와 모델 호출(CallRecord)을 같이 담는다.

    모델 호출은 step_kind = model_call, CallRecord.step은 tool_name에 담는다.
    """

    __tablename__ = "agent_steps"
    __table_args__ = (
        CheckConstraint(
            "step_kind IN ('code_tool', 'fixed_stage', 'decide', 'check', 'model_call')",
            name="ck_agent_steps_step_kind",
        ),
        # StepRecord: ok/failed/waiting, CallRecord: ok/cache_hit/transport_error/…
        CheckConstraint(
            "outcome IN ('ok', 'failed', 'waiting', 'cache_hit', 'transport_error', "
            "'limit_exceeded', 'invalid_output')",
            name="ck_agent_steps_outcome",
        ),
    )

    # 자동 증가 숫자: 기록된 순서를 그대로 보인다
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    step_kind: Mapped[str] = mapped_column(Text)
    tool_name: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text)
    # 지휘 단계 칸 (StepRecord)
    reason: Mapped[str | None] = mapped_column(Text)
    result_status: Mapped[str | None] = mapped_column(Text)
    result_id: Mapped[str | None] = mapped_column(Text)  # 만든 결과 ID (예: oa_results.id)
    model_call_count: Mapped[int | None] = mapped_column(Integer)
    # 모델 호출 칸 (CallRecord)
    model: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)
    from_cache: Mapped[bool | None] = mapped_column(Boolean)
    attempt: Mapped[int | None] = mapped_column(Integer)
    transport_try: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApiCache(Base):
    """외부 API 응답 캐시. 외부 API 호출은 이 캐시와 호출 상한을 거친다 (core/llm/cache.py)."""

    __tablename__ = "api_cache"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
