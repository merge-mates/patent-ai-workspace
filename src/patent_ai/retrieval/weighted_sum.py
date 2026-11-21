"""점수 가중합 검색 구현. impl 이름 weighted_sum (이슈 #212, cite-search design 7-6절).

BM25와 벡터 점수를 각각 min-max로 [0, 1]에 맞춘 뒤 가중합으로 섞는다 (RRF는 순위만 쓰지만
이쪽은 점수 크기를 쓴다). 안쪽 검색기는 get_searcher로 만든다.
core를 import하지 않는다. 모델 호출 없음.
"""

from datetime import date

from patent_ai.retrieval.contract import Embed, get_searcher, register_impl
from patent_ai.retrieval.errors import ModeNotSupportedError
from patent_ai.retrieval.hybrid import read_weights
from patent_ai.retrieval.repository import ChunkRepository
from patent_ai.retrieval.schemas import Corpus, Mode, SearchHit, SearchResult, SearchScope


def min_max(scores: dict[str, float]) -> dict[str, float]:
    """chunk_id -> 점수를 [0, 1]로 맞춘다. 전부 같은 점수면 모두 1.0."""
    if not scores:
        return {}
    lo, hi = min(scores.values()), max(scores.values())
    if hi == lo:
        return {cid: 1.0 for cid in scores}
    return {cid: (s - lo) / (hi - lo) for cid, s in scores.items()}


def _read_weighted_sum_settings(settings: dict) -> dict[str, float]:
    """settings['weighted_sum']['weights']를 검사한다 (hybrid 가중치와 같은 규칙)."""
    cfg = settings.get("weighted_sum")
    if not isinstance(cfg, dict):
        raise ValueError("settings에 weighted_sum 칸(weights)이 없다")
    return read_weights(cfg.get("weights"), "weighted_sum")


@register_impl("weighted_sum")
class WeightedSumSearcher:
    def __init__(self, repo: ChunkRepository, settings: dict, embed: Embed | None = None) -> None:
        self._repo = repo
        self._index_version: str = settings["index_version"]
        self._weights = _read_weighted_sum_settings(settings)
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
        if mode != "hybrid":
            raise ModeNotSupportedError(
                f"weighted_sum 구현은 hybrid 방식만 한다 (받은 값 {mode!r})"
            )
        base = {
            "corpus": corpus,
            "index_version": self._index_version,
            "mode": mode,
            "scope": SearchScope(doc_ids=doc_ids, as_of=as_of, k=k),
        }
        n = self._repo.count_chunks(corpus, self._index_version, doc_ids)
        if n == 0:
            return SearchResult(**base, status="unverified", status_reason="body_missing")

        # 두 쪽 모두 범위 안 전체 순위(k=n). BM25는 0점 조각을 안 돌려주므로 그쪽 항은 0
        parts = {
            "bm25": self._bm25.search(query, corpus, "bm25", n, doc_ids=doc_ids, as_of=as_of),
            "vector": self._vector.search(query, corpus, "vector", n, doc_ids=doc_ids, as_of=as_of),
        }
        by_id = {h.chunk_id: h for r in parts.values() for h in r.hits}
        scores: dict[str, float] = {}
        for method, r in parts.items():
            # 방식마다 돌려준 조각들끼리 min-max로 [0, 1]에 맞춘 뒤 가중치를 곱해 더한다
            normed = min_max({h.chunk_id: h.score for h in r.hits})
            for cid, s in normed.items():
                scores[cid] = scores.get(cid, 0.0) + self._weights[method] * s
        skipped = max(r.skipped_unverified_edition for r in parts.values())

        # 점수 내림차순, 같으면 chunk_id 오름차순 (계약)
        order = sorted(scores, key=lambda cid: (-scores[cid], cid))[:k]
        hits = [
            SearchHit(**by_id[cid].model_dump(exclude={"score", "rank"}), score=scores[cid], rank=i)
            for i, cid in enumerate(order, start=1)
        ]
        if not hits:
            return SearchResult(
                **base, status="not_found_in_scope", skipped_unverified_edition=skipped
            )
        return SearchResult(**base, skipped_unverified_edition=skipped, hits=hits)
