"""claim_versions amendment event check

Revision ID: b7e2c4a91d03
Revises: 0cdd6516da57
Create Date: 2026-11-19 22:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e2c4a91d03"
down_revision: str | Sequence[str] | None = "0cdd6516da57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """보정서 판(source_kind = 'amendment')은 case_event_id가 꼭 있다 (#120 리뷰 (가), #16)."""
    op.create_check_constraint(
        "ck_claim_versions_amendment_event",
        "claim_versions",
        "source_kind <> 'amendment' OR case_event_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_claim_versions_amendment_event", "claim_versions", type_="check")
