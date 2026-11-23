"""agent_steps unit_id tool_input

Revision ID: f1a6c3d8b905
Revises: a9d4c7e1b526
Create Date: 2026-11-23 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f1a6c3d8b905"
down_revision: str | Sequence[str] | None = "a9d4c7e1b526"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """다시 찾기 도구 줄에 판단 단위와 넘긴 입력을 남긴다 (#309). 옛 줄은 NULL."""
    op.add_column("agent_steps", sa.Column("unit_id", sa.Text(), nullable=True))
    op.add_column(
        "agent_steps",
        sa.Column("tool_input", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_steps", "tool_input")
    op.drop_column("agent_steps", "unit_id")
