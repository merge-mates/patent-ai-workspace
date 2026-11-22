"""2단계 하이브리드 검색 구현. impl 이름 two_stage (이슈 #212, cite-search design 7-6절).

1단계 BM25가 범위 안에서 위 N개 후보를 고르고, 2단계에서 그 후보만 벡터 유사도로 다시 줄세운다.
안쪽 검색기는 get_searcher로 만든다 (계약 검사 래퍼를 그대로 거침).
core를 import하지 않는다. 모델 호출 없음 (질의 벡터는 부르는 쪽 embed나 기록된 질의 벡터 파일).
"""

from datetime import date

from patent_ai.retrieval.contract import Embed, get_searcher, register_impl
from patent_ai.retrieval.errors import ModeNotSupportedError
from patent_ai.retrieval.repository import ChunkRepository
from patent_ai.retrieval.schemas import Corpus, Mode, SearchHit, SearchResult, SearchScope


def _read_two_stage_settings(settings: dict) -> int:
    """settings['two_stage']['candidates']를 검사한다. 없거나 이상하면 기본값 없이 멈춘다."""
    cfg = settings.get("two_stage")
    if not isinstance(cfg, dict):
        raise ValueError("settings에 two_stage 칸(candidates)이 없다")
    n = cfg.get("candidates")
    # bool은 int의 하위 타입이라 따로 막는다
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise ValueError(f"two_stage.candidates는 1 이상의 정수여야 한다: {n!r}")
    return n


@register_impl("two_stage")
class TwoStageSearcher:
    def __init__(self, repo: ChunkRepository, settings: dict, embed: Embed | None = None) -> None:
        self._repo = repo
        self._index_version: str = settings["index_version"]
        self._candidates = _read_two_stage_settings(settings)
        self._bm25 = get_searcher("bm25", repo, settings)
        self._vector = get_searcher("vector", repo, settings, embed)

    def search(
        self,
        query: str,
        corpus: Corpus,
        mode: Mode,
        k: int,
        doc_ids: list[str] | None = None,
        as_of: date | None = None,
    ) -> SearchResult:
        # Mode는 bm25/vector/hybrid뿐이라 2단계도 hybrid 이름으로 부른다
        if mode != "hybrid":
            raise ModeNotSupportedError(f"two_stage 구현은 hybrid 방식만 한다 (받은 값 {mode!r})")
        base = {
            "corpus": corpus,
            "index_version": self._index_version,
            "mode": mode,
            "scope": SearchScope(doc_ids=doc_ids, as_of=as_of, k=k),
        }
        n = self._repo.count_chunks(corpus, self._index_version, doc_ids)
        if n == 0:
            return SearchResult(**base, status="unverified", status_reason="body_missing")

        # 1단계: BM25 위 N개가 후보
        first = self._bm25.search(
            query, corpus, "bm25", self._candidates, doc_ids=doc_ids, as_of=as_of
        )
        candidate_ids = {h.chunk_id for h in first.hits}
        if not candidate_ids:
            # BM25 후보가 없으면 순수 벡터로 되돌아가지 않는다. 2단계는 "BM25가 걸러 낸 것만"
            # 벡터로 줄세우는 방식이라, 되돌아가면 다른 방식 결과를 이 방식 이름으로 내는 셈이다
            return SearchResult(
                **base,
                status="not_found_in_scope",
                skipped_unverified_edition=first.skipped_unverified_edition,
            )

        # 2단계: 범위 안 전체 벡터 순위(k=n)에서 후보만 남긴다 (벡터 순서 유지)
        second = self._vector.search(query, corpus, "vector", n, doc_ids=doc_ids, as_of=as_of)
        kept = [h for h in second.hits if h.chunk_id in candidate_ids]
        # 점수 내림차순, 같으면 chunk_id 오름차순 (계약)
        kept.sort(key=lambda h: (-h.score, h.chunk_id))
        skipped = max(first.skipped_unverified_edition, second.skipped_unverified_edition)
        hits = [
            SearchHit(**h.model_dump(exclude={"rank"}), rank=i)
            for i, h in enumerate(kept[:k], start=1)
        ]
        if not hits:
            return SearchResult(
                **base, status="not_found_in_scope", skipped_unverified_edition=skipped
            )
        return SearchResult(**base, skipped_unverified_edition=skipped, hits=hits)
