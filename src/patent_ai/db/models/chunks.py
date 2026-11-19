"""검색 조각 표 두 개 (design.md 5-1절). 칸은 같고 표 이름과 색인 판 CHECK만 다르다.

칸 이름은 retrieval/schemas.py의 Chunk와 맞춘다 (location -> loc_*, edition -> edition_*).
db는 retrieval을 import하지 않는다.
"""

from datetime import date, datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import ARRAY, CheckConstraint, DateTime, Index, Integer, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from patent_ai.db.base import Base


class ChunkColumns:
    """두 조각 표가 같이 쓰는 칸."""

    # 내용으로 정한 ID: <index_version>:<doc_id>:<위치 키>
    chunk_id: Mapped[str] = mapped_column(Text, primary_key=True)
    index_version: Mapped[str] = mapped_column(Text)
    doc_id: Mapped[str] = mapped_column(Text)
    chunk_kind: Mapped[str] = mapped_column(Text)
    loc_kind: Mapped[str] = mapped_column(Text)
    loc_start: Mapped[int | None] = mapped_column(Integer)
    loc_end: Mapped[int | None] = mapped_column(Integer)
    loc_figures: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), server_default=text("'{}'::integer[]")
    )
    loc_claims: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), server_default=text("'{}'::integer[]")
    )
    loc_label: Mapped[str] = mapped_column(Text)
    # 법령 판본을 모르면 unverified. 빈칸(NULL)은 안 된다
    edition_status: Mapped[str] = mapped_column(Text)
    edition_effective_from: Mapped[date | None]
    edition_effective_to: Mapped[date | None]
    edition_label: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    # 길이를 정하지 않은 vector: 색인 판마다 모델이 달라도 담는다. 인덱스 없음
    embedding: Mapped[list[float] | None] = mapped_column(VECTOR(dim=None))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LawChunk(ChunkColumns, Base):
    __tablename__ = "law_chunks"
    __table_args__ = (
        CheckConstraint("index_version ~ '^law-idx-v[0-9]+$'", name="ck_law_chunks_index_version"),
        CheckConstraint(
            "edition_status IN ('confirmed', 'unverified', 'not_applicable')",
            name="ck_law_chunks_edition_status",
        ),
        Index("ix_law_chunks_index_version_doc_id", "index_version", "doc_id"),
        # 기준일로 판본을 거를 때 쓴다 (법령 표만)
        Index(
            "ix_law_chunks_index_version_edition_from", "index_version", "edition_effective_from"
        ),
    )


class CiteChunk(ChunkColumns, Base):
    __tablename__ = "cite_chunks"
    __table_args__ = (
        CheckConstraint(
            "index_version ~ '^cite-idx-v[0-9]+$'", name="ck_cite_chunks_index_version"
        ),
        CheckConstraint(
            "edition_status IN ('confirmed', 'unverified', 'not_applicable')",
            name="ck_cite_chunks_edition_status",
        ),
        Index("ix_cite_chunks_index_version_doc_id", "index_version", "doc_id"),
    )
