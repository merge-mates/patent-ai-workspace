"""direction_selections 표와 runs.kind 더하기 (사람 방향 선택 기록, 초안만 다시 만드는 실행)

Revision ID: c6e1a4f8b237
Revises: b3f8d2e6a914
Create Date: 2026-11-22 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c6e1a4f8b237"
down_revision: str | Sequence[str] | None = "b3f8d2e6a914"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """#70: 사람이 고른 방향을 쌓아 두는 표, 실행 종류 칸(full / redo_drafts)."""
    op.create_table(
        "direction_selections",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("oa_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("unit_id", sa.Text(), nullable=False),
        sa.Column("candidate_id", sa.Text(), nullable=True),
        sa.Column("written_direction", sa.Text(), nullable=True),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "origin IN ('human_selected', 'human_written')", name="ck_direction_selections_origin"
        ),
        sa.CheckConstraint(
            "(candidate_id IS NULL) <> (written_direction IS NULL)",
            name="ck_direction_selections_one_of",
        ),
        sa.ForeignKeyConstraint(["oa_id"], ["oas.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_direction_selections_run_id", "direction_selections", ["run_id"])
    op.create_index(
        "ix_direction_selections_oa_unit_created",
        "direction_selections",
        ["oa_id", "unit_id", "created_at"],
    )
    # 이미 있는 실행은 모두 끝까지 도는 실행이었다 (server_default로 채운다)
    op.add_column("runs", sa.Column("kind", sa.Text(), server_default="full", nullable=False))
    op.create_check_constraint("ck_runs_kind", "runs", "kind IN ('full', 'redo_drafts')")


def downgrade() -> None:
    op.drop_constraint("ck_runs_kind", "runs", type_="check")
    op.drop_column("runs", "kind")
    op.drop_index("ix_direction_selections_oa_unit_created", table_name="direction_selections")
    op.drop_index("ix_direction_selections_run_id", table_name="direction_selections")
    op.drop_table("direction_selections")
