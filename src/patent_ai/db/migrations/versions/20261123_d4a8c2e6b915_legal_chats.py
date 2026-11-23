"""legal_chats·legal_chat_turns 표 더하기 (법률 질문 대화 저장)

Revision ID: d4a8c2e6b915
Revises: f1c8b3e7a925
Create Date: 2026-11-23 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d4a8c2e6b915"
down_revision: str | Sequence[str] | None = "f1c8b3e7a925"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """#29 task-2: 사건 없이 여러 번 묻는 법률 질문 대화와 그 턴 (묶음은 턴 줄 jsonb)."""
    op.create_table(
        "legal_chats",
        sa.Column("chat_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.PrimaryKeyConstraint("chat_id"),
    )
    op.create_index("ix_legal_chats_case_id", "legal_chats", ["case_id"])
    op.create_table(
        "legal_chat_turns",
        sa.Column("chat_id", sa.Text(), nullable=False),
        sa.Column("no", sa.Integer(), nullable=False),
        sa.Column("question", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("scope_changed", sa.Boolean(), nullable=False),
        sa.Column("bundle", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("no >= 1", name="ck_legal_chat_turns_no"),
        sa.ForeignKeyConstraint(["chat_id"], ["legal_chats.chat_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chat_id", "no"),
    )


def downgrade() -> None:
    op.drop_table("legal_chat_turns")
    op.drop_index("ix_legal_chats_case_id", table_name="legal_chats")
    op.drop_table("legal_chats")
