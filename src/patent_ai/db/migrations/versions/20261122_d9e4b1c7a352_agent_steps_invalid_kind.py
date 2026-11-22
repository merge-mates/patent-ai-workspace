"""agent_steps invalid_kind

Revision ID: d9e4b1c7a352
Revises: b3f8d2e6a914
Create Date: 2026-11-22 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d9e4b1c7a352"
down_revision: str | Sequence[str] | None = "b3f8d2e6a914"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """출력 검사에 떨어진 모델 호출의 오류 종류(짧은 코드)를 남긴다 (#228)."""
    op.add_column("agent_steps", sa.Column("invalid_kind", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_steps", "invalid_kind")
