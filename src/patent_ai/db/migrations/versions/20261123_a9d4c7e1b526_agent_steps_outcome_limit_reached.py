"""agent_steps outcome에 limit_reached 추가

Revision ID: a9d4c7e1b526
Revises: d4a8c2e6b915
Create Date: 2026-11-23 15:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9d4c7e1b526"
down_revision: str | Sequence[str] | None = "d4a8c2e6b915"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_agent_steps_outcome"
_OLD = (
    "outcome IN ('ok', 'failed', 'waiting', 'skipped', 'cache_hit', 'transport_error', "
    "'limit_exceeded', 'invalid_output', 'output_truncated')"
)
_NEW = (
    "outcome IN ('ok', 'failed', 'waiting', 'skipped', 'limit_reached', 'cache_hit', "
    "'transport_error', 'limit_exceeded', 'invalid_output', 'output_truncated')"
)


def upgrade() -> None:
    """호출 상한에 닿아 못 돈 단계를 outcome = 'limit_reached'로 적을 수 있게 한다 (#241)."""
    op.drop_constraint(CONSTRAINT, "agent_steps", type_="check")
    op.create_check_constraint(CONSTRAINT, "agent_steps", _NEW)


def downgrade() -> None:
    # 옛 CHECK는 limit_reached를 못 받으니 먼저 skipped로 되돌린다
    op.execute("UPDATE agent_steps SET outcome = 'skipped' WHERE outcome = 'limit_reached'")
    op.drop_constraint(CONSTRAINT, "agent_steps", type_="check")
    op.create_check_constraint(CONSTRAINT, "agent_steps", _OLD)
