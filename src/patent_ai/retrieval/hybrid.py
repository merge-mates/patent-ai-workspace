"""하이브리드 검색 구현 (cite-search design 7-4절). impl 이름 hybrid.

BM25와 벡터 두 검색기의 순위를 RRF(Reciprocal Rank Fusion)로 섞는다.
안쪽 검색기는 get_searcher로 만든다 (계약 검사 래퍼를 그대로 거침).
core를 import하지 않는다. 모델 호출 없음 (질의 벡터는 부르는 쪽 embed나 녹화 파일).
"""

import math
from datetime import date

from patent_ai.retrieval.contract import Embed, get_searcher, register_impl
from patent_ai.retrieval.errors import ModeNotSupportedError
from patent_ai.retrieval.repository import ChunkRepository
from patent_ai.retrieval.schemas import (
    ChunkKind,
    Corpus,
    Mode,
    SearchHit,
    SearchResult,
    SearchScope,
    SourceKind,
)

_METHODS = {"bm25", "vector"}


def rrf(ranked: dict[str, list[str]], weights: dict[str, float], rrf_k: int) -> dict[str, float]:
    """방식별 순위 목록(1위부터)을 섞어 chunk_id -> 점수로 돌려준다.

    점수 = 방식마다 weight / (rrf_k + 순위)를 더한 값. 그 방식 목록에 없으면 그 항은 0.
    """
    scores: dict[str, float] = {}
    for method, ids in ranked.items():
        for rank, chunk_id in enumerate(ids, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + weights[method] / (rrf_k + rank)
    return scores


def _read_hybrid_settings(settings: dict) -> tuple[int, dict[str, float]]:
    """settings['hybrid']를 검사한다. 칸이 없거나 이상하면 기본값으로 때우지 않고 멈춘다."""
    cfg = settings.get("hybrid")
    if not isinstance(cfg, dict):
        raise ValueError("settings에 hybrid 칸(rrf_k, weights)이 없다")
    rrf_k = cfg.get("rrf_k")
    # bool은 int의 하위 타입이라 따로 막는다
    if not isinstance(rrf_k, int) or isinstance(rrf_k, bool) or rrf_k <= 0:
        raise ValueError(f"hybrid.rrf_k는 1 이상의 정수여야 한다: {rrf_k!r}")
    weights = cfg.get("weights")
    if not isinstance(weights, dict) or set(weights) != _METHODS:
        raise ValueError(f"hybrid.weights 키는 bm25, vector여야 한다: {weights!r}")
    if any(
        isinstance(w, bool) or not isinstance(w, int | float) or not math.isfinite(w) or w < 0
        for w in weights.values()
    ):
        raise ValueError(f"hybrid.weights는 0 이상의 유한한 숫자여야 한다: {weights!r}")
    if sum(weights.values()) == 0:
        raise ValueError("hybrid.weights가 둘 다 0이다")
    return rrf_k, {m: float(w) for m, w in weights.items()}


@register_impl("hybrid")
class HybridSearcher:
    def __init__(self, repo: ChunkRepository, settings: dict, embed: Embed | None = None) -> None:
        self._repo = repo
        self._index_version: str = settings["index_version"]
        self._rrf_k, self._weights = _read_hybrid_settings(settings)
        # 안쪽 둘도 계약 검사 래퍼를 거친다
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
        *,
        chunk_kinds: list[ChunkKind] | None = None,
        source_kinds: list[SourceKind] | None = None,
        decided_on_or_before: date | None = None,
    ) -> SearchResult:
        if mode != "hybrid":
            raise ModeNotSupportedError(f"hybrid 구현은 hybrid 방식만 한다 (받은 값 {mode!r})")
        base = {
            "corpus": corpus,
            "index_version": self._index_version,
            "mode": mode,
            "scope": SearchScope(
                doc_ids=doc_ids,
                as_of=as_of,
                k=k,
                chunk_kinds=chunk_kinds,
                source_kinds=source_kinds,
                decided_on_or_before=decided_on_or_before,
            ),
        }
        # 안쪽 검색기에 같은 거르기를 넘긴다
        flt = {
            "chunk_kinds": chunk_kinds,
            "source_kinds": source_kinds,
            "decided_on_or_before": decided_on_or_before,
        }
        # 문헌·자료 유형으로 거른 조각이 하나도 없으면 본문이 없는 것. 안쪽을 부르지 않는다
        n = self._repo.count_chunks(
            corpus, self._index_version, doc_ids, chunk_kinds=chunk_kinds, source_kinds=source_kinds
        )
        if n == 0:
            return SearchResult(**base, status="unverified", status_reason="body_missing")

        # 두 쪽 모두 범위 안 전체 순위(k=n)를 받아 섞는다. BM25는 0점 조각을 안 돌려준다
        parts = {
            "bm25": self._bm25.search(
                query, corpus, "bm25", n, doc_ids=doc_ids, as_of=as_of, **flt
            ),
            "vector": self._vector.search(
                query, corpus, "vector", n, doc_ids=doc_ids, as_of=as_of, **flt
            ),
        }
        ranked = {m: [h.chunk_id for h in r.hits] for m, r in parts.items()}
        by_id = {h.chunk_id: h for r in parts.values() for h in r.hits}
        scores = rrf(ranked, self._weights, self._rrf_k)
        # 건수는 두 쪽 중 큰 값 (같은 범위를 세므로 보통 같다)
        skipped = max(r.skipped_unverified_edition for r in parts.values())
        unknown_date = max(r.skipped_unknown_date for r in parts.values())
        extra = {"skipped_unverified_edition": skipped, "skipped_unknown_date": unknown_date}

        # 점수 내림차순, 같으면 chunk_id 오름차순 (계약)
        order = sorted(scores, key=lambda cid: (-scores[cid], cid))[:k]
        hits = [
            SearchHit(**by_id[cid].model_dump(exclude={"score", "rank"}), score=scores[cid], rank=i)
            for i, cid in enumerate(order, start=1)
        ]
        if not hits:
            return SearchResult(**base, status="not_found_in_scope", **extra)
        return SearchResult(**base, **extra, hits=hits)
