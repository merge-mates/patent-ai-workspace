"""법률 질문 대화 표 둘 (이슈 #29, docs/data-model.md 6절).

대화(`legal_chats`) 하나에 턴(`legal_chat_turns`)이 쌓인다. 묶음(④)은 턴 줄의 jsonb에 통째로 둔다.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from patent_ai.db.base import Base


class LegalChat(Base):
    """사건 없이도 여러 번 묻고 답하는 대화 하나. case_id는 사건에 붙여 물었을 때만."""

    __tablename__ = "legal_chats"

    chat_id: Mapped[str] = mapped_column(Text, primary_key=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LegalChatTurn(Base):
    """대화의 한 턴: 질문 + 시점·자료 유형이 앞 질문과 달라졌는지 + 답(LegalEvidenceBundle)."""

    __tablename__ = "legal_chat_turns"
    __table_args__ = (CheckConstraint("no >= 1", name="ck_legal_chat_turns_no"),)

    chat_id: Mapped[str] = mapped_column(
        ForeignKey("legal_chats.chat_id", ondelete="CASCADE"), primary_key=True
    )
    no: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    question: Mapped[dict[str, Any]] = mapped_column(JSONB)  # LegalQuestion.model_dump(mode="json")
    scope_changed: Mapped[bool] = mapped_column(Boolean)
    bundle: Mapped[dict[str, Any]] = mapped_column(JSONB)  # LegalEvidenceBundle.model_dump
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
