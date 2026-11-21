"""documents에 citation_key 추가 (올린 인용문헌이 어느 인용문헌 답인지)

Revision ID: a7c3e9f2d815
Revises: e5d3a7b92c18
Create Date: 2026-11-21 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c3e9f2d815"
# [머지 순서] #206(f6a2c9d1b4e7, step_results)도 e5d3a7b92c18 위에 있다.
# #206이 먼저 머지되면 이 값을 "f6a2c9d1b4e7"로 바꿔 한 줄로 만든다 (db/CLAUDE.md).
down_revision: str | Sequence[str] | None = "e5d3a7b92c18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """인용문헌 본문 문서에 인용문헌 번호 키를 남긴다 (#201). 있던 줄은 비운다(모름)."""
    op.add_column("documents", sa.Column("citation_key", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "citation_key")
