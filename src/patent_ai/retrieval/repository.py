"""조각 저장소 (design.md 5-1절). 메모리 저장소(테스트·--chunks)와 Postgres 저장소.

core를 import하지 않는다. Postgres 저장소는 같은 Protocol로 같은 거르기를 한다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import and_, create_engine, false, func, or_, select
from sqlalchemy.orm import Session

from patent_ai.db.models.chunks import (
    DATED_SOURCE_KINDS,
    CiteChunk,
    LawChunk,
    check_cite_chunk_meta,
    check_law_chunk,
)
from patent_ai.index_version import is_index_version
from patent_ai.retrieval.schemas import (
    Chunk,
    ChunkKind,
    Corpus,
    Edition,
    Location,
    SourceKind,
)
from patent_ai.settings import get_settings


class ChunkRepository(Protocol):
    """조각을 읽고 센다. 색인 판·문헌·기준일·자료 유형·선고일 거르기는 구현이 같게 한다.

    chunk_kinds·source_kinds·decided_on_or_before는 키워드 전용이고 None이면 안 건다.
    """

    def chunks(
        self,
        corpus: Corpus,
        index_version: str,
        doc_ids: list[str] | None = None,
        as_of: date | None = None,
        *,
        chunk_kinds: list[ChunkKind] | None = None,
        source_kinds: list[SourceKind] | None = None,
        decided_on_or_before: date | None = None,
    ) -> list[Chunk]:
        """조건에 맞는 조각. 결과 순서는 보장하지 않는다."""
        ...

    def has_index_version(self, corpus: Corpus, index_version: str) -> bool: ...

    def count_chunks(
        self,
        corpus: Corpus,
        index_version: str,
        doc_ids: list[str] | None = None,
        *,
        chunk_kinds: list[ChunkKind] | None = None,
        source_kinds: list[SourceKind] | None = None,
        decided_on_or_before: date | None = None,
    ) -> int: ...

    def count_unverified_edition(
        self,
        corpus: Corpus,
        index_version: str,
        doc_ids: list[str] | None = None,
        *,
        chunk_kinds: list[ChunkKind] | None = None,
        source_kinds: list[SourceKind] | None = None,
        decided_on_or_before: date | None = None,
    ) -> int: ...

    def count_unknown_date(
        self,
        corpus: Corpus,
        index_version: str,
        doc_ids: list[str] | None = None,
        chunk_kinds: list[ChunkKind] | None = None,
        source_kinds: list[SourceKind] | None = None,
    ) -> int:
        """선고일을 몰라(decided_on null) 날짜 거르기에서 빠질 판례·심결 조각 수."""
        ...

    def earliest_effective_from(
        self,
        corpus: Corpus,
        index_version: str,
        chunk_kinds: list[ChunkKind],
        source_kinds: list[SourceKind] | None = None,
    ) -> date | None:
        """그 유형 조각 중 가장 이른 판의 시행 시작일. 판본이 확인된(시작일 있는) 조각만 본다.

        없으면 None (유형 조각 0개, 판본 모름만, 판례·심결). 기준일이 이보다 앞서면
        '그 시점 판이 색인에 없다'는 재료다.
        """
        ...


def fill_law_defaults(chunk: Chunk) -> Chunk:
    """law 조각의 source_kind가 없으면 statute로 채운다 (v1·v2 JSONL은 조문뿐).

    마이그레이션이 옛 DB 행을 statute로 채운 것과 같아서, 옛 JSONL을 다시 넣어도 내용 지문이 같다.
    """
    if chunk.source_kind is None:
        return chunk.model_copy(update={"source_kind": "statute"})
    return chunk


def chunk_problem(corpus: Corpus, chunk: Chunk) -> str | None:
    """표에 맞지 않는 조각이면 이유 한 줄 (db의 검사 함수를 부른다. 넣기·덤프도 같은 함수)."""
    if corpus == "law":
        chunk = fill_law_defaults(chunk)  # source_kind 빈 조각은 채운 값(statute)으로 판단한다
        return check_law_chunk(
            chunk.chunk_kind,
            chunk.edition.status,
            chunk.source_kind,
            chunk.decided_on,
            chunk.speaker,
        )
    return check_cite_chunk_meta(chunk.source_kind, chunk.decided_on, chunk.speaker, chunk.attrs)


def _check_lists(
    doc_ids: list[str] | None,
    chunk_kinds: list[ChunkKind] | None = None,
    source_kinds: list[SourceKind] | None = None,
) -> None:
    # None만 "전체"다. 빈 목록은 실수일 가능성이 커서 조용히 0건을 돌려주지 않고 막는다
    for name, value in (
        ("doc_ids", doc_ids),
        ("chunk_kinds", chunk_kinds),
        ("source_kinds", source_kinds),
    ):
        if value is not None and len(value) == 0:
            raise ValueError(f"{name}가 빈 목록이다. 전체는 None으로 표현한다")


def _date_unknown(chunk: Chunk) -> bool:
    """판례·심결인데 선고일을 모르는 조각 (날짜 거르기에서 빠지고 skipped_unknown_date로 센다)."""
    return chunk.source_kind in DATED_SOURCE_KINDS and chunk.decided_on is None


def _passes_date(chunk: Chunk, cutoff: date) -> bool:
    """선고일 거르기: 조문·심사기준은 통과, 판례·심결은 선고일 <= cutoff만 (날짜 모름은 뺀다)."""
    if chunk.source_kind not in DATED_SOURCE_KINDS:
        return True
    return chunk.decided_on is not None and chunk.decided_on <= cutoff


def _edition_unknown(chunk: Chunk) -> bool:
    """판본을 모르는 조각: unverified, 또는 confirmed인데 시작일이 없는 조각.

    규칙: as_of 검색에서 빠지는 판본 모름 조각은 모두 count_unverified_edition에 센다.
    """
    ed = chunk.edition
    return ed.status == "unverified" or (ed.status == "confirmed" and ed.effective_from is None)


def _in_force(chunk: Chunk, as_of: date) -> bool:
    """그 날짜에 시행 중인 판본인가. effective_from <= as_of <= effective_to (끝 없으면 현행)."""
    ed = chunk.edition
    if _edition_unknown(chunk):
        return False  # 판본을 모르면 기준일 검색에서 뺀다 (센 것은 count_unverified_edition)
    if ed.status == "not_applicable":
        return True  # 인용문헌은 판본이 없어 기준일로 거르지 않는다
    assert ed.effective_from is not None  # 위에서 걸러졌다 (타입 검사용)
    if as_of < ed.effective_from:
        return False
    return ed.effective_to is None or as_of <= ed.effective_to


class InMemoryChunkRepository:
    def __init__(self, tables: dict[Corpus, list[Chunk]]):
        # law 조각의 source_kind 빈 칸은 statute로 채운다 (Postgres 행은 NOT NULL statute와 같게)
        self._tables = {
            corpus: [fill_law_defaults(c) for c in rows] if corpus == "law" else rows
            for corpus, rows in tables.items()
        }

    @classmethod
    def from_jsonl(cls, corpus: Corpus, *paths: str | Path) -> InMemoryChunkRepository:
        """JSONL 줄마다 Chunk 하나. Chunk에 말뭉치 칸이 없어서 어느 표인지 인자로 받는다."""
        rows: list[Chunk] = []
        seen: set[str] = set()
        for path in paths:
            for no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    chunk = Chunk.model_validate_json(line)
                except ValueError as e:
                    # 어느 파일 몇 번째 줄이 왜 깨졌는지 한 줄로 알린다
                    first = e.errors()[0]["msg"] if hasattr(e, "errors") else str(e)
                    raise ValueError(f"{path}:{no} 조각 JSON을 못 읽는다: {first}") from e
                # 말뭉치와 색인 판 앞말이 다르면 (law 표에 cite-idx-v1) 막는다
                if not is_index_version(corpus, chunk.index_version):
                    raise ValueError(
                        f"{path}:{no} 색인 판 {chunk.index_version!r}이 {corpus}와 안 맞는다"
                    )
                # law는 판본이 있어야 하고 cite는 판본이 없어야 한다 (표가 섞이면 막는다)
                na = chunk.edition.status == "not_applicable"
                if corpus == "cite" and not na:
                    raise ValueError(
                        f"{path}:{no} {corpus} 표에 맞지 않는 판본 상태 {chunk.edition.status!r}"
                    )
                if corpus == "law":
                    chunk = fill_law_defaults(chunk)
                reason = chunk_problem(corpus, chunk)
                if reason:
                    raise ValueError(f"{path}:{no} {reason}")
                if chunk.chunk_id in seen:
                    raise ValueError(f"{path}:{no} chunk_id가 겹친다: {chunk.chunk_id}")
                seen.add(chunk.chunk_id)
                rows.append(chunk)
        return cls({corpus: rows})

    @classmethod
    def merge(cls, *repos: InMemoryChunkRepository) -> InMemoryChunkRepository:
        """말뭉치마다 만든 저장소를 하나로 합친다. 같은 말뭉치가 둘이면 이어 붙인다."""
        tables: dict[Corpus, list[Chunk]] = {}
        for repo in repos:
            for corpus, rows in repo._tables.items():
                tables.setdefault(corpus, []).extend(rows)
        for corpus, rows in tables.items():
            ids = [c.chunk_id for c in rows]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{corpus} 표에 chunk_id가 겹친다")
        return cls(tables)

    def _scope(
        self,
        corpus: Corpus,
        index_version: str,
        doc_ids: list[str] | None,
        chunk_kinds: list[ChunkKind] | None = None,
        source_kinds: list[SourceKind] | None = None,
        decided_on_or_before: date | None = None,
    ) -> list[Chunk]:
        _check_lists(doc_ids, chunk_kinds, source_kinds)
        allowed = None if doc_ids is None else set(doc_ids)
        rows = [
            c
            for c in self._tables.get(corpus, [])
            if c.index_version == index_version
            and (allowed is None or c.doc_id in allowed)
            and (chunk_kinds is None or c.chunk_kind in chunk_kinds)
            and (source_kinds is None or c.source_kind in source_kinds)
        ]
        if decided_on_or_before is not None:
            rows = [c for c in rows if _passes_date(c, decided_on_or_before)]
        return rows

    def chunks(
        self,
        corpus: Corpus,
        index_version: str,
        doc_ids: list[str] | None = None,
        as_of: date | None = None,
        *,
        chunk_kinds: list[ChunkKind] | None = None,
        source_kinds: list[SourceKind] | None = None,
        decided_on_or_before: date | None = None,
    ) -> list[Chunk]:
        rows = self._scope(
            corpus, index_version, doc_ids, chunk_kinds, source_kinds, decided_on_or_before
        )
        if as_of is not None:
            rows = [c for c in rows if _in_force(c, as_of)]
        return rows

    def has_index_version(self, corpus: Corpus, index_version: str) -> bool:
        return any(c.index_version == index_version for c in self._tables.get(corpus, []))

    def count_chunks(
        self,
        corpus: Corpus,
        index_version: str,
        doc_ids: list[str] | None = None,
        *,
        chunk_kinds: list[ChunkKind] | None = None,
        source_kinds: list[SourceKind] | None = None,
        decided_on_or_before: date | None = None,
    ) -> int:
        rows = self._scope(
            corpus, index_version, doc_ids, chunk_kinds, source_kinds, decided_on_or_before
        )
        return len(rows)

    def count_unverified_edition(
        self,
        corpus: Corpus,
        index_version: str,
        doc_ids: list[str] | None = None,
        *,
        chunk_kinds: list[ChunkKind] | None = None,
        source_kinds: list[SourceKind] | None = None,
        decided_on_or_before: date | None = None,
    ) -> int:
        rows = self._scope(
            corpus, index_version, doc_ids, chunk_kinds, source_kinds, decided_on_or_before
        )
        return sum(1 for c in rows if _edition_unknown(c))

    def count_unknown_date(
        self,
        corpus: Corpus,
        index_version: str,
        doc_ids: list[str] | None = None,
        chunk_kinds: list[ChunkKind] | None = None,
        source_kinds: list[SourceKind] | None = None,
    ) -> int:
        rows = self._scope(corpus, index_version, doc_ids, chunk_kinds, source_kinds)
        return sum(1 for c in rows if _date_unknown(c))

    def earliest_effective_from(
        self,
        corpus: Corpus,
        index_version: str,
        chunk_kinds: list[ChunkKind],
        source_kinds: list[SourceKind] | None = None,
    ) -> date | None:
        rows = self._scope(corpus, index_version, None, chunk_kinds, source_kinds)
        starts = [
            c.edition.effective_from
            for c in rows
            if c.edition.status == "confirmed" and c.edition.effective_from is not None
        ]
        return min(starts, default=None)


# ---- Postgres 저장소 ----

_TABLES: dict[str, type[LawChunk] | type[CiteChunk]] = {"law": LawChunk, "cite": CiteChunk}


def chunk_to_row(corpus: Corpus, chunk: Chunk) -> LawChunk | CiteChunk:
    """Chunk를 그 말뭉치 표의 행으로 바꾼다 (location -> loc_*, edition -> edition_*)."""
    loc, ed = chunk.location, chunk.edition
    # 새 칸 넷은 법령 표에만 있다 (인용문헌 표에는 칸이 없다)
    extra: dict[str, Any] = {}
    if corpus == "law":
        chunk = fill_law_defaults(chunk)  # source_kind 빈 조각은 statute (NOT NULL)
        extra = {
            "source_kind": chunk.source_kind,
            "decided_on": chunk.decided_on,
            "speaker": chunk.speaker,
            "attrs": chunk.attrs,
        }
    return _TABLES[corpus](
        chunk_id=chunk.chunk_id,
        index_version=chunk.index_version,
        doc_id=chunk.doc_id,
        chunk_kind=chunk.chunk_kind,
        loc_kind=loc.kind,
        loc_start=loc.start,
        loc_end=loc.end,
        loc_figures=list(loc.figures),
        loc_claims=list(loc.claims),
        loc_label=loc.label,
        edition_status=ed.status,
        edition_effective_from=ed.effective_from,
        edition_effective_to=ed.effective_to,
        edition_label=ed.label,
        text=chunk.text,
        embedding=chunk.embedding,
        **extra,
    )


def row_to_chunk(row: LawChunk | CiteChunk) -> Chunk:
    """표의 행을 Chunk로 되돌린다."""
    emb: Any = row.embedding
    return Chunk(
        chunk_id=row.chunk_id,
        index_version=row.index_version,
        doc_id=row.doc_id,
        chunk_kind=row.chunk_kind,  # type: ignore[arg-type]
        location=Location(
            kind=row.loc_kind,  # type: ignore[arg-type]
            start=row.loc_start,
            end=row.loc_end,
            label=row.loc_label,
            figures=list(row.loc_figures or []),
            claims=list(row.loc_claims or []),
        ),
        edition=Edition(
            status=row.edition_status,  # type: ignore[arg-type]
            effective_from=row.edition_effective_from,
            effective_to=row.edition_effective_to,
            label=row.edition_label,
        ),
        text=row.text,
        # pgvector는 numpy 배열로 돌려줄 수 있어 파이썬 list로 바꾼다
        embedding=None if emb is None else [float(x) for x in emb],
        # 인용문헌 행에는 새 칸이 없어 None
        source_kind=getattr(row, "source_kind", None),
        decided_on=getattr(row, "decided_on", None),
        speaker=getattr(row, "speaker", None),
        attrs=getattr(row, "attrs", None),
    )


class PostgresChunkRepository:
    """세션 하나로 조각 표를 읽는다. 거르기 규칙은 InMemoryChunkRepository와 같다."""

    def __init__(self, session: Session):
        self._session = session

    @classmethod
    def from_url(cls, url: str | None = None) -> PostgresChunkRepository:
        """DB 주소로 저장소를 만든다. 주소가 없으면 설정의 DATABASE_URL (design 7-1 채점기)."""
        engine = create_engine(url or get_settings().database_url)
        return cls(Session(engine))

    def _where(
        self,
        corpus: Corpus,
        index_version: str,
        doc_ids: list[str] | None,
        chunk_kinds: list[ChunkKind] | None = None,
        source_kinds: list[SourceKind] | None = None,
        decided_on_or_before: date | None = None,
    ):
        _check_lists(doc_ids, chunk_kinds, source_kinds)
        t = _TABLES[corpus]
        conds = [t.index_version == index_version]
        if doc_ids is not None:
            conds.append(t.doc_id.in_(doc_ids))
        if chunk_kinds is not None:
            conds.append(t.chunk_kind.in_(chunk_kinds))
        # 새 칸(source_kind·decided_on)은 법령 표에만 있다. 인용문헌 조각은 source_kind가 없다
        if corpus == "law":
            if source_kinds is not None:
                conds.append(t.source_kind.in_(source_kinds))
            if decided_on_or_before is not None:
                # 조문·심사기준은 통과, 판례·심결은 선고일 <= 기준일만 (날짜 모름은 뺀다)
                conds.append(
                    or_(
                        t.source_kind.not_in(DATED_SOURCE_KINDS),
                        and_(t.decided_on.is_not(None), t.decided_on <= decided_on_or_before),
                    )
                )
        elif source_kinds is not None:
            conds.append(false())
        return t, conds

    @staticmethod
    def _unknown(t):
        # 판본 모름: unverified, 또는 confirmed인데 시작일 없음 (_edition_unknown과 같다)
        return or_(
            t.edition_status == "unverified",
            and_(t.edition_status == "confirmed", t.edition_effective_from.is_(None)),
        )

    @staticmethod
    def _in_force(t, as_of: date):
        # 인용문헌(not_applicable)은 거르지 않고, confirmed는 시작일 <= 기준일 <= 끝일(없으면 현행)
        return or_(
            t.edition_status == "not_applicable",
            and_(
                t.edition_status == "confirmed",
                t.edition_effective_from <= as_of,
                or_(t.edition_effective_to.is_(None), as_of <= t.edition_effective_to),
            ),
        )

    def chunks(
        self,
        corpus: Corpus,
        index_version: str,
        doc_ids: list[str] | None = None,
        as_of: date | None = None,
        *,
        chunk_kinds: list[ChunkKind] | None = None,
        source_kinds: list[SourceKind] | None = None,
        decided_on_or_before: date | None = None,
    ) -> list[Chunk]:
        t, conds = self._where(
            corpus, index_version, doc_ids, chunk_kinds, source_kinds, decided_on_or_before
        )
        if as_of is not None:
            conds.append(self._in_force(t, as_of))
        rows = self._session.scalars(select(t).where(*conds)).all()
        return [row_to_chunk(r) for r in rows]

    def has_index_version(self, corpus: Corpus, index_version: str) -> bool:
        t = _TABLES[corpus]
        return (
            self._session.scalar(select(select(t).where(t.index_version == index_version).exists()))
            is True
        )

    def count_chunks(
        self,
        corpus: Corpus,
        index_version: str,
        doc_ids: list[str] | None = None,
        *,
        chunk_kinds: list[ChunkKind] | None = None,
        source_kinds: list[SourceKind] | None = None,
        decided_on_or_before: date | None = None,
    ) -> int:
        t, conds = self._where(
            corpus, index_version, doc_ids, chunk_kinds, source_kinds, decided_on_or_before
        )
        return self._session.scalar(select(func.count()).select_from(t).where(*conds)) or 0

    def count_unverified_edition(
        self,
        corpus: Corpus,
        index_version: str,
        doc_ids: list[str] | None = None,
        *,
        chunk_kinds: list[ChunkKind] | None = None,
        source_kinds: list[SourceKind] | None = None,
        decided_on_or_before: date | None = None,
    ) -> int:
        t, conds = self._where(
            corpus, index_version, doc_ids, chunk_kinds, source_kinds, decided_on_or_before
        )
        conds.append(self._unknown(t))
        return self._session.scalar(select(func.count()).select_from(t).where(*conds)) or 0

    def count_unknown_date(
        self,
        corpus: Corpus,
        index_version: str,
        doc_ids: list[str] | None = None,
        chunk_kinds: list[ChunkKind] | None = None,
        source_kinds: list[SourceKind] | None = None,
    ) -> int:
        t, conds = self._where(corpus, index_version, doc_ids, chunk_kinds, source_kinds)
        if corpus != "law":
            return 0  # 인용문헌 조각은 선고일 개념이 없다
        conds.append(and_(t.source_kind.in_(DATED_SOURCE_KINDS), t.decided_on.is_(None)))
        return self._session.scalar(select(func.count()).select_from(t).where(*conds)) or 0

    def earliest_effective_from(
        self,
        corpus: Corpus,
        index_version: str,
        chunk_kinds: list[ChunkKind],
        source_kinds: list[SourceKind] | None = None,
    ) -> date | None:
        t, conds = self._where(corpus, index_version, None, chunk_kinds, source_kinds)
        # 메모리 저장소와 같게: 판본이 확인되고 시작일이 있는 조각만
        conds.append(t.edition_status == "confirmed")
        return self._session.scalar(select(func.min(t.edition_effective_from)).where(*conds))
