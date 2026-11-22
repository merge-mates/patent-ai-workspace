"""법령 색인 한 판을 메모리에 읽어 검색기까지 만든다 (법률 질문 탭용, 이슈 #29).

api는 이 함수를 lru_cache로 감싸 부르기만 한다 (api -> core -> retrieval 방향).
읽은 뒤 DB 세션은 닫고, 캐시에는 메모리 조각만 남는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from patent_ai.core.f2_legal_research.run import F2Settings
from patent_ai.core.f2_legal_research.tools import LawPool
from patent_ai.retrieval.contract import Searcher, get_searcher
from patent_ai.retrieval.repository import InMemoryChunkRepository, PostgresChunkRepository


@dataclass(frozen=True)
class LegalIndex:
    """법령 색인 한 판: 조각 묶음(pool)과 검색기. 프로세스에 한 번만 만든다."""

    pool: LawPool
    searcher: Searcher


def open_law_repo() -> PostgresChunkRepository:
    """진짜 법령 조각 저장소 (DATABASE_URL). 테스트는 이 함수를 바꾼다."""
    return PostgresChunkRepository.from_url()


def load_legal_index(settings: F2Settings) -> LegalIndex:
    """색인 조각을 한 번 읽어 메모리에 두고 검색기를 만든다. 읽은 뒤 DB 세션은 닫는다.

    색인 판이 없거나 조각이 0개면 예외 (호출하는 쪽이 캐시하지 않고 "확인되지 않음"으로 낸다).
    """
    iv = settings.index_version
    repo = open_law_repo()
    try:
        if not repo.has_index_version("law", iv):
            raise RuntimeError(f"법령 색인 {iv}이 저장소에 없음")
        pool = LawPool.load(repo, iv)
    finally:
        repo.close()
    if not pool.chunks:
        raise RuntimeError(f"법령 색인 {iv}의 조각이 0개")
    # 검색기는 메모리 repo 위에 만들어 DB를 다시 보지 않는다
    mem_repo = InMemoryChunkRepository({"law": list(pool.chunks)})
    searcher = get_searcher(
        settings.search_method, mem_repo, {"index_version": iv, "tokenizer": settings.tokenizer}
    )
    return LegalIndex(pool, searcher)
