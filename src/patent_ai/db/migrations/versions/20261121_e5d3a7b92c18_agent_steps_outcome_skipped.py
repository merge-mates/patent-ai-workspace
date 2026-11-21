"""agent_steps outcome에 skipped 추가

Revision ID: e5d3a7b92c18
Revises: b7e2c4a91d03
Create Date: 2026-11-21 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5d3a7b92c18"
# 임시 순서: #181(c4a8f1e63b27, output_truncated)이 먼저 머지되면 down_revision을 그 위로 옮기고
# 아래 목록에 output_truncated를 같이 둔다.
down_revision: str | Sequence[str] | None = "b7e2c4a91d03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "ck_agent_steps_outcome"
_OLD = (
    "outcome IN ('ok', 'failed', 'waiting', 'cache_hit', 'transport_error', "
    "'limit_exceeded', 'invalid_output')"
)
_NEW = (
    "outcome IN ('ok', 'failed', 'waiting', 'skipped', 'cache_hit', 'transport_error', "
    "'limit_exceeded', 'invalid_output')"
)


def upgrade() -> None:
    """넘긴 단계(자료·도구 없음)를 outcome = 'skipped'로 적을 수 있게 한다 (#57 T5)."""
    op.drop_constraint(CONSTRAINT, "agent_steps", type_="check")
    op.create_check_constraint(CONSTRAINT, "agent_steps", _NEW)


def downgrade() -> None:
    # 옛 CHECK는 skipped를 못 받으니 먼저 waiting으로 되돌린다
    op.execute("UPDATE agent_steps SET outcome = 'waiting' WHERE outcome = 'skipped'")
    op.drop_constraint(CONSTRAINT, "agent_steps", type_="check")
    op.create_check_constraint(CONSTRAINT, "agent_steps", _OLD)
