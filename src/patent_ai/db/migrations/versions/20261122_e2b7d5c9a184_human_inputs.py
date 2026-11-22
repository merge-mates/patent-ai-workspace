"""human_inputs 표 더하기 (사람이 넣은 번호와 OA 정리 확인)

Revision ID: e2b7d5c9a184
Revises: c6e1a4f8b237
Create Date: 2026-11-22 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2b7d5c9a184"
down_revision: str | Sequence[str] | None = "c6e1a4f8b237"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """#70 계획 ②: 사람이 넣은 출원번호·발송번호, 정리 결과 "맞아요"를 쌓아 두는 표."""
    op.create_table(
        "human_inputs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("oa_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('application_number', 'dispatch_number', 'oa_result_confirmed')",
            name="ck_human_inputs_kind",
        ),
        sa.CheckConstraint(
            "(kind = 'oa_result_confirmed') = (value IS NULL)", name="ck_human_inputs_value"
        ),
        sa.ForeignKeyConstraint(["oa_id"], ["oas.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_human_inputs_run_id", "human_inputs", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_human_inputs_run_id", table_name="human_inputs")
    op.drop_table("human_inputs")
