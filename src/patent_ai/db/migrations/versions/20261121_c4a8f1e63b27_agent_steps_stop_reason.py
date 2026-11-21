"""agent_steps stop_reason and output_truncated outcome

Revision ID: c4a8f1e63b27
Revises: b7e2c4a91d03
Create Date: 2026-11-21 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4a8f1e63b27"
down_revision: str | Sequence[str] | None = "b7e2c4a91d03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "outcome IN ('ok', 'failed', 'waiting', 'cache_hit', 'transport_error', "
    "'limit_exceeded', 'invalid_output')"
)
_NEW = (
    "outcome IN ('ok', 'failed', 'waiting', 'cache_hit', 'transport_error', "
    "'limit_exceeded', 'invalid_output', 'output_truncated')"
)


def upgrade() -> None:
    """모델 호출 기록에 답을 끝낸 이유(stop_reason)를 남기고, 잘린 답을 따로 적는다 (#172)."""
    op.add_column("agent_steps", sa.Column("stop_reason", sa.Text(), nullable=True))
    # CHECK는 고칠 수 없어 지우고 새 값 목록으로 다시 만든다
    op.drop_constraint("ck_agent_steps_outcome", "agent_steps", type_="check")
    op.create_check_constraint("ck_agent_steps_outcome", "agent_steps", _NEW)


def downgrade() -> None:
    # output_truncated 줄이 남아 있으면 옛 CHECK를 못 만드니 invalid_output으로 되돌린다
    op.execute(
        "UPDATE agent_steps SET outcome = 'invalid_output' WHERE outcome = 'output_truncated'"
    )
    op.drop_constraint("ck_agent_steps_outcome", "agent_steps", type_="check")
    op.create_check_constraint("ck_agent_steps_outcome", "agent_steps", _OLD)
    op.drop_column("agent_steps", "stop_reason")
