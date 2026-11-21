"""step_results table for F3·F4 results

Revision ID: f6a2c9d1b4e7
Revises: e5d3a7b92c18
Create Date: 2026-11-21 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f6a2c9d1b4e7"
down_revision: str | Sequence[str] | None = "e5d3a7b92c18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUS_CHECK = "status IN ('confirmed', 'unverified', 'not_found_in_scope', 'conflict')"


def upgrade() -> None:
    """실행이 낸 F3·F4 결과를 실행·단계마다 한 줄로 저장한다 (#191)."""
    op.create_table(
        "step_results",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("oa_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('f3', 'f4')", name="ck_step_results_kind"),
        sa.CheckConstraint(_STATUS_CHECK, name="ck_step_results_status"),
        sa.ForeignKeyConstraint(["oa_id"], ["oas.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "kind", name="uq_step_results_run_kind"),
    )
    op.create_index("ix_step_results_oa_id", "step_results", ["oa_id"])


def downgrade() -> None:
    op.drop_index("ix_step_results_oa_id", table_name="step_results")
    op.drop_table("step_results")
