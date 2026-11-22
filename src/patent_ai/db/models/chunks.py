"""검색 조각 표 두 개 (design.md 5-1절). 칸은 같고 표 이름과 색인 판 CHECK만 다르다.

칸 이름은 retrieval/schemas.py의 Chunk와 맞춘다 (location -> loc_*, edition -> edition_*).
db는 retrieval을 import하지 않는다.
"""

from datetime import date, datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import ARRAY, CheckConstraint, DateTime, Index, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
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
    # 법령 표에만 있는 칸 (design 5-1). 인용문헌 표는 그대로
    source_kind: Mapped[str] = mapped_column(Text)
    decided_on: Mapped[date | None]
    speaker: Mapped[str | None] = mapped_column(Text)
    attrs: Mapped[dict | None] = mapped_column(JSONB)
    __table_args__ = (
        CheckConstraint("index_version ~ '^law-idx-v[0-9]+$'", name="ck_law_chunks_index_version"),
        CheckConstraint(
            "edition_status IN ('confirmed', 'unverified', 'not_applicable')",
            name="ck_law_chunks_edition_status",
        ),
        CheckConstraint(
            "source_kind IN ('statute', 'guideline', 'precedent', 'trial')",
            name="ck_law_chunks_source_kind",
        ),
        CheckConstraint("speaker IN ('court', 'party', 'unknown')", name="ck_law_chunks_speaker"),
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


# ---- 넣기 전 검사 ----
# retrieval 넣기·저장소와 db 덤프가 같이 부른다. db는 retrieval을 import 못 해 문자열만 받는다.
_JUDGMENT_KINDS = {"judgment", "judgment_summary"}
# 선고일이 있어야 하는 자료 유형 (판례·심결). 저장소의 날짜 거르기도 이 상수를 쓴다
DATED_SOURCE_KINDS = ("precedent", "trial")


def check_law_chunk(
    chunk_kind: str,
    edition_status: str,
    source_kind: str | None,
    decided_on: object | None = None,
    speaker: str | None = None,
) -> str | None:
    """법령 표(law_chunks)에 넣을 수 있는 조각인가. 안 되면 이유 한 줄, 되면 None.

    - 판본 not_applicable은 판례·심결 조각(chunk_kind가 judgment·judgment_summary)만.
    - 선고일·발언 주체는 source_kind가 precedent·trial일 때만 값이 있을 수 있다.
    - 판례·심결 chunk_kind(judgment·judgment_summary)는 source_kind가 precedent·trial이어야 하고,
      source_kind statute는 chunk_kind article만. source_kind None은 채우기(fill) 전 값이라 통과
      (호출하는 쪽이 채운 뒤 값으로 부른다).
    """
    if edition_status == "not_applicable" and chunk_kind not in _JUDGMENT_KINDS:
        return (
            f"판본 not_applicable은 판례·심결 조각만 법령 표에 넣는다 (chunk_kind {chunk_kind!r})"
        )
    if source_kind is not None:
        if chunk_kind in _JUDGMENT_KINDS and source_kind not in DATED_SOURCE_KINDS:
            return (
                f"판례·심결 chunk_kind {chunk_kind!r}는 source_kind가 precedent·trial이어야 한다 "
                f"({source_kind!r})"
            )
        if source_kind == "statute" and chunk_kind != "article":
            return f"source_kind statute는 chunk_kind article만 가진다 ({chunk_kind!r})"
    if (decided_on is not None or speaker is not None) and source_kind not in DATED_SOURCE_KINDS:
        return f"decided_on·speaker는 판례·심결 조각만 가진다 (source_kind {source_kind!r})"
    return None


def check_cite_chunk_meta(
    source_kind: str | None,
    decided_on: object | None,
    speaker: str | None,
    attrs: dict | None,
) -> str | None:
    """인용문헌 조각은 법령 표 새 칸(source_kind·decided_on·speaker·attrs)이 모두 비어야 한다."""
    if any(v is not None for v in (source_kind, decided_on, speaker, attrs)):
        return "인용문헌 조각에는 source_kind·decided_on·speaker·attrs를 넣지 않는다"
    return None
