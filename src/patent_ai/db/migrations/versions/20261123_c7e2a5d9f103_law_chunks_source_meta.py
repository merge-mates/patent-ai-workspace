"""law_chunks에 자료 유형·선고일·발언 주체·속성 칸 더하기 (law-idx-v3, 이슈 #24)

Revision ID: c7e2a5d9f103
Revises: b3f8d2e6a914
Create Date: 2026-11-23 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c7e2a5d9f103"
down_revision: str | Sequence[str] | None = "b3f8d2e6a914"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """v1·v2 행은 모두 조문이라 source_kind를 statute로 채운 뒤 NOT NULL로 바꾼다."""
    op.add_column("law_chunks", sa.Column("source_kind", sa.Text(), nullable=True))
    op.add_column("law_chunks", sa.Column("decided_on", sa.Date(), nullable=True))
    op.add_column("law_chunks", sa.Column("speaker", sa.Text(), nullable=True))
    op.add_column("law_chunks", sa.Column("attrs", postgresql.JSONB(), nullable=True))
    op.execute("UPDATE law_chunks SET source_kind = 'statute'")
    op.alter_column("law_chunks", "source_kind", nullable=False)
    op.create_check_constraint(
        "ck_law_chunks_source_kind",
        "law_chunks",
        "source_kind IN ('statute', 'guideline', 'precedent', 'trial')",
    )
    op.create_check_constraint(
        "ck_law_chunks_speaker", "law_chunks", "speaker IN ('court', 'party', 'unknown')"
    )


def downgrade() -> None:
    # v3 조각(심사기준·판례·심결)이 있어도 칸만 지운다. 되돌린 뒤에는 v3를 다시 넣는다
    op.drop_constraint("ck_law_chunks_speaker", "law_chunks", type_="check")
    op.drop_constraint("ck_law_chunks_source_kind", "law_chunks", type_="check")
    op.drop_column("law_chunks", "attrs")
    op.drop_column("law_chunks", "speaker")
    op.drop_column("law_chunks", "decided_on")
    op.drop_column("law_chunks", "source_kind")
