"""F2 검색 도구와 출처 확인 (design 7-1 도구 표, 2절 3·4단계). 모두 코드, 모델을 부르지 않는다.

- 아는 조문은 ID 조회(`get_article`), 모르는 근거는 검색(`search_article`). design 5절.
- 심사기준·판례·심결은 `law-idx-v3`(#24) 전이라 조각이 없다. 그때는 `search`를 부르지 않고
  `unverified(body_missing)`로 남긴다 (못 찾음 ≠ 없음).
- 출처 확인(`check_source`)은 무조건 도는 코드 단계다: 없는 출처 0건을 코드로 보장한다.
"""

import logging
import re
from dataclasses import dataclass
from datetime import date

from patent_ai.core.f2_legal_research.refs import ArticleRef
from patent_ai.core.schemas.common import Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.legal_evidence import LegalSourceKind, SearchLogEntry
from patent_ai.retrieval.contract import Searcher
from patent_ai.retrieval.repository import ChunkRepository
from patent_ai.retrieval.schemas import Chunk, SearchResult

logger = logging.getLogger(__name__)

CORPUS = "law"
# 법령 doc_id 꼴: <법 이름>_<MST>_<시행일 8자리> (retrieval/law_index._RAW_NAME)
_LAW_DOC = re.compile(r"^(?P<law>.+)_[0-9]+_[0-9]{8}$")
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class ArticleLookup:
    """조문 ID 조회 결과. chunk가 있으면 status는 confirmed, 없으면 그 이유."""

    ref: ArticleRef
    as_of: date
    chunk: Chunk | None
    status: Status
    log: SearchLogEntry
    conflicts: tuple[Chunk, ...] = ()  # 같은 날 시행판이 둘 이상일 때 그 조각들 (사람이 볼 것)


def _law_of(doc_id: str) -> str | None:
    m = _LAW_DOC.match(doc_id)
    return m["law"] if m else None


def _scope(ref: ArticleRef, index_version: str, as_of: date) -> str:
    return f"{index_version} 법령 조문 {ref.label}, 모든 판 (기준일 {as_of.isoformat()})"


def get_article(
    repo: ChunkRepository, index_version: str, ref: ArticleRef, as_of: date
) -> ArticleLookup:
    """그날 시행 중인 그 법의 그 조·항 조각 하나를 읽는다."""

    def same_article(c: Chunk) -> bool:
        # 시행령(`특허법_시행령_…`)은 법 이름이 달라 섞이지 않는다
        return (
            c.chunk_kind == "article"
            and _law_of(c.doc_id) == ref.law
            and c.location.start == ref.loc
        )

    # 판본 거르기 없이 그 조문의 모든 판 (판본 모름 조각을 세려고)
    every = [c for c in repo.chunks(CORPUS, index_version) if same_article(c)]
    in_force = [c for c in repo.chunks(CORPUS, index_version, as_of=as_of) if same_article(c)]
    # 판본 모름: unverified, 또는 confirmed인데 시작일이 없는 조각
    # (repository._edition_unknown과 같은 규칙)
    unknown = [
        c
        for c in every
        if c.edition.status == "unverified"
        or (c.edition.status == "confirmed" and c.edition.effective_from is None)
    ]
    log = SearchLogEntry(
        source_kind=LegalSourceKind.STATUTE,
        index_version=index_version,
        as_of=as_of,
        queries=1,
        hits=len(in_force),
        skipped_unverified_edition=len(unknown),
    )
    if len(in_force) == 1:
        chunk = in_force[0]
        checked = f"{ref.label} {chunk.edition.label or chunk.doc_id} 판본·위치 확인"
        return ArticleLookup(
            ref, as_of, chunk, Status(value=StatusValue.CONFIRMED, checked=checked), log
        )
    if len(in_force) > 1:
        # 같은 날 시행판이 둘이면 판본 표가 틀린 것: 하나를 고르지 않는다
        logger.warning("get_article: %s %s 시행판이 %d개", ref.label, as_of, len(in_force))
        return ArticleLookup(
            ref, as_of, None, Status(value=StatusValue.CONFLICT), log, tuple(in_force)
        )
    if unknown or every:
        # 판본 모름 조각만 있거나, 그 조문의 다른 판은 있는데 그날 판이 색인에 없음
        # (예: 2017.9.22판보다 앞선 날). 그날 글을 모르니 "없음"이 아니라 확인되지 않음이다.
        # 법령 API로 그 판을 조회하는 길은 다음 계획 (design 4절 ②)
        if not unknown:
            logger.warning(
                "get_article: %s %s 시행판이 색인에 없음 (다른 판만 있음)", ref.label, as_of
            )
        return ArticleLookup(
            ref,
            as_of,
            None,
            Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.EDITION_UNKNOWN),
            log,
        )
    # 어느 판에도 그 조문이 없음: 찾아본 범위 안에 없다
    return ArticleLookup(
        ref,
        as_of,
        None,
        Status(
            value=StatusValue.NOT_FOUND_IN_SCOPE, searched_scope=_scope(ref, index_version, as_of)
        ),
        log,
    )


def search_article(searcher: Searcher, query: str, as_of: date | None, k: int) -> SearchResult:
    """조문 번호 없이 찾을 때: 질의(심사관 논리 글)로 법령 조각을 BM25 검색한다."""
    return searcher.search(query, CORPUS, "bm25", k, as_of=as_of)


def _count_kind(repo: ChunkRepository, index_version: str, kind: str) -> int:
    return sum(1 for c in repo.chunks(CORPUS, index_version) if c.chunk_kind == kind)


def _not_indexed(
    repo: ChunkRepository, index_version: str, kind: str, source: LegalSourceKind, as_of
) -> tuple[Status, SearchLogEntry]:
    """그 유형 조각이 없으면 search를 부르지 않고 body_missing (design 2절 3단계)."""
    n = _count_kind(repo, index_version, kind)
    if n:
        # law-idx-v3(#24) 전에는 생기지 않는 길. 다음 계획에서 검색을 붙인다
        logger.warning("%s 조각 %d개가 있지만 F2 검색은 아직 없음 (확인되지 않음으로 둠)", kind, n)
    log = SearchLogEntry(
        source_kind=source, index_version=index_version, as_of=as_of, queries=0, hits=0
    )
    return Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.BODY_MISSING), log


def search_guideline(
    repo: ChunkRepository, index_version: str, as_of: date | None
) -> tuple[Status, SearchLogEntry]:
    return _not_indexed(repo, index_version, "guideline", LegalSourceKind.GUIDELINE, as_of)


def search_precedent(
    repo: ChunkRepository, index_version: str, as_of: date | None
) -> tuple[Status, SearchLogEntry]:
    return _not_indexed(repo, index_version, "judgment", LegalSourceKind.PRECEDENT, as_of)


def _squash(text: str) -> str:
    return _SPACE.sub("", text)


def check_source(
    repo: ChunkRepository,
    index_version: str,
    chunk_id: str | None,
    raw_text: str | None,
    as_of: date | None,
) -> bool:
    """출처 확인: 조각이 색인에 있고, 인용 글이 조각 글에 그대로(공백 무시) 있고, 기준일 판인가."""
    if not chunk_id or not raw_text or not _squash(raw_text):
        return False
    pool = repo.chunks(CORPUS, index_version, as_of=as_of)
    found = next((c for c in pool if c.chunk_id == chunk_id), None)
    if found is None:
        return False  # 없는 조각이거나 기준일에 시행 중인 판이 아님
    return _squash(raw_text) in _squash(found.text)
