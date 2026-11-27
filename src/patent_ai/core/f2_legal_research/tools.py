"""F2 검색 도구와 출처 확인 (design 7-1 도구 표, 2절 3·4단계). 모두 코드, 모델을 부르지 않는다.

- 아는 조문은 ID 조회(`get_article`), 모르는 근거는 검색(`search_article`). design 5절.
- 심사기준·판례·심결 검색은 `source_search.py`에 있다.
- 출처 확인(`check_source`)은 무조건 도는 코드 단계다: 없는 출처 0건을 코드로 보장한다.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date

from patent_ai.core.f2_legal_research.refs import ArticleRef
from patent_ai.core.schemas.common import Evidence, Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.legal_evidence import (
    FurtherReview,
    FurtherReviewWhy,
    LegalSource,
    LegalSourceKind,
    SearchLogEntry,
)
from patent_ai.retrieval.contract import Searcher
from patent_ai.retrieval.repository import ChunkRepository
from patent_ai.retrieval.schemas import Chunk, ChunkKind, SearchResult

logger = logging.getLogger(__name__)

CORPUS = "law"
# 판례·심결 조각 종류 (요지·전문). 판례인지 심결인지는 source_kind로 가른다
CASE_KINDS: list[ChunkKind] = ["judgment_summary", "judgment"]
# 법령 doc_id 꼴: <법 이름>_<MST>_<시행일 8자리> (retrieval/law_index._RAW_NAME)
_LAW_DOC = re.compile(r"^(?P<law>.+)_[0-9]+_[0-9]{8}$")
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class LawPool:
    """law corpus 한 색인 판의 조각을 한 번만 읽어 둔 것 (실행 하나 안에서 같이 쓴다).

    Postgres에서 조각 1만여 개를 도구마다 다시 읽지 않으려고 둔다 (#222 리뷰).
    기준일 거르기는 저장소(retrieval/repository.py `_in_force`)와 같은 규칙을 메모리에서 한다.
    """

    index_version: str
    chunks: tuple[Chunk, ...]

    @classmethod
    def load(cls, repo: ChunkRepository, index_version: str) -> LawPool:
        return cls(index_version, tuple(repo.chunks(CORPUS, index_version)))

    def in_force(self, as_of: date) -> list[Chunk]:
        """그 날짜에 시행 중인 조각. 판본 모름은 빼고, not_applicable(판례 등)은 남긴다."""
        return [c for c in self.chunks if _in_force(c, as_of)]


def edition_unknown(chunk: Chunk) -> bool:
    """판본 모름: unverified, 또는 confirmed인데 시작일이 없는 조각 (repository와 같은 규칙)."""
    ed = chunk.edition
    return ed.status == "unverified" or (ed.status == "confirmed" and ed.effective_from is None)


def _in_force(chunk: Chunk, as_of: date) -> bool:
    ed = chunk.edition
    if edition_unknown(chunk):
        return False
    if ed.status == "not_applicable":
        return True
    assert ed.effective_from is not None  # 위에서 걸러졌다 (타입 검사용)
    return ed.effective_from <= as_of and (ed.effective_to is None or as_of <= ed.effective_to)


@dataclass(frozen=True)
class ArticleLookup:
    """조문 ID 조회 결과. chunk가 있으면 status는 confirmed, 없으면 그 이유."""

    ref: ArticleRef
    as_of: date
    chunk: Chunk | None
    status: Status
    log: SearchLogEntry
    conflicts: tuple[Chunk, ...] = ()  # 같은 날 시행판이 둘 이상일 때 그 조각들 (사람이 볼 것)


def law_of(doc_id: str) -> str | None:
    m = _LAW_DOC.match(doc_id)
    return m["law"] if m else None


def _scope(ref: ArticleRef, index_version: str, as_of: date) -> str:
    return f"{index_version} 법령 조문 {ref.label}, 모든 판 (기준일 {as_of.isoformat()})"


def get_article(pool: LawPool, ref: ArticleRef, as_of: date) -> ArticleLookup:
    """그날 시행 중인 그 법의 그 조·항 조각 하나를 읽는다."""

    def same_article(c: Chunk) -> bool:
        # 시행령(`특허법_시행령_…`)은 법 이름이 달라 섞이지 않는다
        return (
            c.chunk_kind == "article"
            and law_of(c.doc_id) == ref.law
            and c.location.start == ref.loc
        )

    # 판본 거르기 없이 그 조문의 모든 판 (판본 모름 조각을 세려고)
    index_version = pool.index_version
    every = [c for c in pool.chunks if same_article(c)]
    in_force = [c for c in every if _in_force(c, as_of)]
    unknown = [c for c in every if edition_unknown(c)]

    def log(status: Status) -> SearchLogEntry:
        return SearchLogEntry(
            source_kind=LegalSourceKind.STATUTE,
            index_version=index_version,
            as_of=as_of,
            queries=1,
            hits=len(in_force),
            skipped_unverified_edition=len(unknown),
            status=status,
        )

    def done(status: Status, chunk: Chunk | None = None, conflicts=()) -> ArticleLookup:
        return ArticleLookup(ref, as_of, chunk, status, log(status), tuple(conflicts))

    if len(in_force) == 1:
        chunk = in_force[0]
        checked = f"{ref.label} {chunk.edition.label or chunk.doc_id} 판본·위치 확인"
        return done(Status(value=StatusValue.CONFIRMED, checked=checked), chunk)
    if len(in_force) > 1:
        # 같은 날 시행판이 둘이면 판본 표가 틀린 것: 하나를 고르지 않는다
        logger.warning("get_article: %s %s 시행판이 %d개", ref.label, as_of, len(in_force))
        return done(Status(value=StatusValue.CONFLICT), conflicts=in_force)
    if unknown or every:
        # 판본 모름 조각만 있거나, 그 조문의 다른 판은 있는데 그날 판이 색인에 없음
        # (예: 2017.9.22판보다 앞선 날). 그날 글을 모르니 "없음"이 아니라 확인되지 않음이다.
        # 법령 API로 그 판을 조회하는 길은 다음 계획 (design 4절 ②)
        if not unknown:
            logger.warning(
                "get_article: %s %s 시행판이 색인에 없음 (다른 판만 있음)", ref.label, as_of
            )
        return done(Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.EDITION_UNKNOWN))
    # 어느 판에도 그 조문이 없음: 찾아본 범위 안에 없다
    return done(
        Status(
            value=StatusValue.NOT_FOUND_IN_SCOPE, searched_scope=_scope(ref, index_version, as_of)
        )
    )


def search_article(searcher: Searcher, query: str, as_of: date | None, k: int) -> SearchResult:
    """조문 번호 없이 찾을 때: 질의(심사관 논리 글)로 법령 조각을 BM25 검색한다."""
    # 조문만 찾는다 (v3 색인에는 심사기준·판례 조각도 같은 표에 있다)
    return searcher.search(query, CORPUS, "bm25", k, as_of=as_of, chunk_kinds=["article"])


def _squash(text: str) -> str:
    return _SPACE.sub("", text)


def check_source(
    pool: LawPool,
    chunk_id: str | None,
    raw_text: str | None,
    as_of: date | None,
) -> bool:
    """출처 확인: 조각이 색인에 있고, 인용 글이 조각 글에 그대로(공백 무시) 있고, 기준일 판인가.

    판례·심결은 판본이 없어 선고일(심결일) ≤ 기준일을 본다. 날짜를 모르면 통과하지 못한다.
    """
    if not chunk_id or not raw_text or not _squash(raw_text):
        return False
    candidates = pool.in_force(as_of) if as_of is not None else list(pool.chunks)
    found = next((c for c in candidates if c.chunk_id == chunk_id), None)
    if found is None:
        return False  # 없는 조각이거나 기준일에 시행 중인 판이 아님
    if as_of is not None and found.chunk_kind in CASE_KINDS:
        if found.decided_on is None or found.decided_on > as_of:
            return False  # 그 시점에는 없던 판결이거나 날짜를 모름
    return _squash(raw_text) in _squash(found.text)


# 질문이 자료 유형을 따로 안 고르면 전부 (OA 흐름·법률 질문 탭이 같이 쓴다)
ALL_KINDS = [
    LegalSourceKind.STATUTE,
    LegalSourceKind.GUIDELINE,
    LegalSourceKind.PRECEDENT,
    LegalSourceKind.TRIAL,
]


def edition_text(chunk: Chunk) -> str | None:
    """사람이 읽는 판본: `특허법_1002_20200101 시행 2020-01-01 ~ 현행`. 시작일 모르면 None."""
    ed = chunk.edition
    if ed.status != "confirmed" or ed.effective_from is None:
        return None
    end = ed.effective_to.isoformat() if ed.effective_to else "현행"
    return f"{chunk.doc_id} 시행 {ed.effective_from.isoformat()} ~ {end}"


def statute_source(
    chunk: Chunk, label: str, as_of: date, checked_on: date, pool: LawPool
) -> LegalSource | None:
    """조각 -> 근거. 출처 확인(무조건 도는 코드 단계)에서 빠지면 None."""
    evidence = Evidence(
        document_id=chunk.doc_id,
        location=chunk.location.label,
        raw_text=chunk.text,
        edition=edition_text(chunk),
        checked_on=checked_on,
        chunk_id=chunk.chunk_id,
        index_version=chunk.index_version,
    )
    if not check_source(pool, evidence.chunk_id, evidence.raw_text, as_of):
        return None
    status = Status(
        value=StatusValue.CONFIRMED,
        checked=f"{label} {chunk.edition.label or chunk.doc_id} 판본·위치 확인",
    )
    return LegalSource(
        source_kind=LegalSourceKind.STATUTE, identifier=label, evidence=evidence, status=status
    )


def further_review(chunk: Chunk, label: str, as_of: date) -> FurtherReview:
    """같은 날 시행판이 둘 이상일 때 겹친 조각: 고르지 않고 사람이 볼 것으로 남긴다."""
    return FurtherReview(
        chunk_id=chunk.chunk_id,
        why=FurtherReviewWhy.OTHER_EDITION,
        note=f"{label}: 기준일 {as_of.isoformat()}에 시행판이 둘 이상 (판본 확인 필요)",
        index_version=chunk.index_version,
    )
