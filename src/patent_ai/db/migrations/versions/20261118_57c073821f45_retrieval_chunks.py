"""retrieval chunks

Revision ID: 57c073821f45
Revises:
Create Date: 2026-11-18 23:19:14.547932

"""

from collections.abc import Sequence

import pgvector.sqlalchemy.vector
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "57c073821f45"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """조각 표 두 개(law_chunks, cite_chunks). design.md 5-1."""
    # autogenerate가 빠뜨리는 확장을 표보다 먼저 만든다
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "cite_chunks",
        sa.Column("chunk_id", sa.Text(), nullable=False),
        sa.Column("index_version", sa.Text(), nullable=False),
        sa.Column("doc_id", sa.Text(), nullable=False),
        sa.Column("chunk_kind", sa.Text(), nullable=False),
        sa.Column("loc_kind", sa.Text(), nullable=False),
        sa.Column("loc_start", sa.Integer(), nullable=True),
        sa.Column("loc_end", sa.Integer(), nullable=True),
        sa.Column(
            "loc_figures",
            sa.ARRAY(sa.Integer()),
            server_default=sa.text("'{}'::integer[]"),
            nullable=False,
        ),
        sa.Column(
            "loc_claims",
            sa.ARRAY(sa.Integer()),
            server_default=sa.text("'{}'::integer[]"),
            nullable=False,
        ),
        sa.Column("loc_label", sa.Text(), nullable=False),
        sa.Column("edition_status", sa.Text(), nullable=False),
        sa.Column("edition_effective_from", sa.Date(), nullable=True),
        sa.Column("edition_effective_to", sa.Date(), nullable=True),
        sa.Column("edition_label", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "edition_status IN ('confirmed', 'unverified', 'not_applicable')",
            name="ck_cite_chunks_edition_status",
        ),
        sa.CheckConstraint(
            "index_version ~ '^cite-idx-v[0-9]+$'", name="ck_cite_chunks_index_version"
        ),
        sa.PrimaryKeyConstraint("chunk_id"),
    )
    op.create_index(
        "ix_cite_chunks_index_version_doc_id",
        "cite_chunks",
        ["index_version", "doc_id"],
        unique=False,
    )
    op.create_table(
        "law_chunks",
        sa.Column("chunk_id", sa.Text(), nullable=False),
        sa.Column("index_version", sa.Text(), nullable=False),
        sa.Column("doc_id", sa.Text(), nullable=False),
        sa.Column("chunk_kind", sa.Text(), nullable=False),
        sa.Column("loc_kind", sa.Text(), nullable=False),
        sa.Column("loc_start", sa.Integer(), nullable=True),
        sa.Column("loc_end", sa.Integer(), nullable=True),
        sa.Column(
            "loc_figures",
            sa.ARRAY(sa.Integer()),
            server_default=sa.text("'{}'::integer[]"),
            nullable=False,
        ),
        sa.Column(
            "loc_claims",
            sa.ARRAY(sa.Integer()),
            server_default=sa.text("'{}'::integer[]"),
            nullable=False,
        ),
        sa.Column("loc_label", sa.Text(), nullable=False),
        sa.Column("edition_status", sa.Text(), nullable=False),
        sa.Column("edition_effective_from", sa.Date(), nullable=True),
        sa.Column("edition_effective_to", sa.Date(), nullable=True),
        sa.Column("edition_label", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "edition_status IN ('confirmed', 'unverified', 'not_applicable')",
            name="ck_law_chunks_edition_status",
        ),
        sa.CheckConstraint(
            "index_version ~ '^law-idx-v[0-9]+$'", name="ck_law_chunks_index_version"
        ),
        sa.PrimaryKeyConstraint("chunk_id"),
    )
    op.create_index(
        "ix_law_chunks_index_version_doc_id",
        "law_chunks",
        ["index_version", "doc_id"],
        unique=False,
    )
    op.create_index(
        "ix_law_chunks_index_version_edition_from",
        "law_chunks",
        ["index_version", "edition_effective_from"],
        unique=False,
    )


def downgrade() -> None:
    """표만 지운다. vector 확장은 다른 표가 쓸 수 있어 남긴다."""
    op.drop_index("ix_law_chunks_index_version_edition_from", table_name="law_chunks")
    op.drop_index("ix_law_chunks_index_version_doc_id", table_name="law_chunks")
    op.drop_table("law_chunks")
    op.drop_index("ix_cite_chunks_index_version_doc_id", table_name="cite_chunks")
    op.drop_table("cite_chunks")
