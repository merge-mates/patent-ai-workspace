"""step_results.kind에 f2 더하기 (F2 법률 근거 묶음 저장)

Revision ID: b3f8d2e6a914
Revises: a7c3e9f2d815
Create Date: 2026-11-22 03:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3f8d2e6a914"
down_revision: str | Sequence[str] | None = "a7c3e9f2d815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """실행이 낸 F2 결과(F2Result: 판단 단위마다 법률 근거 묶음)도 같은 표에 한 줄로 둔다 (#28)."""
    op.drop_constraint("ck_step_results_kind", "step_results", type_="check")
    op.create_check_constraint("ck_step_results_kind", "step_results", "kind IN ('f2', 'f3', 'f4')")


def downgrade() -> None:
    # f2 줄이 남아 있으면 제약을 다시 걸 수 없어 실패한다 (데이터를 몰래 지우지 않는다)
    op.drop_constraint("ck_step_results_kind", "step_results", type_="check")
    op.create_check_constraint("ck_step_results_kind", "step_results", "kind IN ('f3', 'f4')")
