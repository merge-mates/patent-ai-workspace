"""cases에 merged_into_case_id 추가 (같은 출원번호 사건에 합친 임시 사건 표시)

Revision ID: f1c8b3e7a925
Revises: e2b7d5c9a184
Create Date: 2026-11-23 02:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1c8b3e7a925"
# 지금 main head(e2b7d5c9a184, human_inputs) 위. #276(c7e2a5d9f103)이 먼저 머지되면
# 이 PR이 main을 받아 down_revision을 그것으로 옮긴다 (head 하나, db/CLAUDE.md)
down_revision: str | Sequence[str] | None = "e2b7d5c9a184"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """합친 임시 사건에 합친 사건 id를 남긴다 (#272). 있던 사건은 비운다(합치지 않음)."""
    op.add_column("cases", sa.Column("merged_into_case_id", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_cases_merged_into_case_id", "cases", "cases", ["merged_into_case_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint("fk_cases_merged_into_case_id", "cases", type_="foreignkey")
    op.drop_column("cases", "merged_into_case_id")
