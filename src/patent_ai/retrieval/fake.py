"""fake 검색 구현 (design.md 7-2절). 실제 모델·DB 없이 계약을 시험하는 용도.

- bm25: 질의 낱말(공백으로 자름)이 조각 낱말과 겹치는 수
- vector: embed(질의)와 조각 벡터의 코사인 유사도. 테스트는 녹화 파일을 읽는 embed를 쓴다
core를 import하지 않는다.
"""

import json
import math
from datetime import date
from pathlib import Path

from patent_ai.retrieval.contract import Embed, register_impl
from patent_ai.retrieval.errors import RecordedEmbeddingMissing
from patent_ai.retrieval.repository import ChunkRepository
from patent_ai.retrieval.schemas import (
    Chunk,
    Corpus,
    Mode,
    SearchHit,
    SearchResult,
    SearchScope,
)


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"벡터 차원이 다르다: {len(a)} != {len(b)}")
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0  # 길이 0 벡터는 비슷함을 말할 수 없다
    return sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb)


def recorded_embed(path: str | Path) -> Embed:
    """녹화해 둔 {질의: 벡터} 파일을 읽는 embed. 실제 모델을 부르지 않는다."""
    with open(path, encoding="utf-8") as f:
        recorded: dict[str, list[float]] = json.load(f)

    def embed(query: str) -> list[float]:
        if query not in recorded:
            raise RecordedEmbeddingMissing(f"녹화에 없는 질의: {query!r}")
        return recorded[query]

    return embed


@register_impl("fake")
class FakeSearcher:
    def __init__(self, repo: ChunkRepository, settings: dict, embed: Embed | None = None) -> None:
        self._repo = repo
        self._index_version: str = settings["index_version"]
        # embed를 안 넘기고 설정에 녹화 파일만 있으면 그 파일을 읽는 embed를 쓴다 (채점기 설정용)
        if embed is None and settings.get("query_vectors"):
            embed = recorded_embed(settings["query_vectors"])
        self._embed = embed

    def _query_vector(self, query: str) -> list[float]:
        if self._embed is None:
            raise ValueError("vector 검색에는 embed(또는 settings['query_vectors'])가 필요하다")
        return self._embed(query)

    def _score(self, chunk: Chunk, mode: Mode, query: str, qvec: list[float] | None) -> float:
        if mode == "bm25":
            # 겹치는 낱말 수 (같은 낱말은 한 번만 센다)
            return float(len(set(query.split()) & set(chunk.text.split())))
        if chunk.embedding is None:
            # 조용히 빠지면 안 된다. 녹화 데이터가 빠진 것이니 오류로 알린다
            raise ValueError(f"조각에 embedding이 없다: {chunk.chunk_id}")
        assert qvec is not None
        return _cosine(qvec, chunk.embedding)

    def search(
        self,
        query: str,
        corpus: Corpus,
        mode: Mode,
        k: int,
        doc_ids: list[str] | None = None,
        as_of: date | None = None,
    ) -> SearchResult:
        scope = SearchScope(doc_ids=doc_ids, as_of=as_of, k=k)
        base = {
            "corpus": corpus,
            "index_version": self._index_version,
            "mode": mode,
            "scope": scope,
        }
        qvec = self._query_vector(query) if mode == "vector" else None

        # 거른 문헌 조각이 0개면 본문이 없는 것 (기준일과 상관없이 문헌 기준)
        if self._repo.count_chunks(corpus, self._index_version, doc_ids) == 0:
            return SearchResult(**base, status="unverified", status_reason="body_missing")

        chunks = self._repo.chunks(corpus, self._index_version, doc_ids, as_of)
        scored = [(self._score(c, mode, query, qvec), c) for c in chunks]
        # 점수 0 이하는 뺀다. 점수 내림차순, 같으면 chunk_id 오름차순
        scored = [(s, c) for s, c in scored if s > 0]
        scored.sort(key=lambda sc: (-sc[0], sc[1].chunk_id))

        # 기준일 검색에서 판본을 몰라 빠진 조각 수
        skipped = (
            self._repo.count_unverified_edition(corpus, self._index_version, doc_ids)
            if as_of is not None
            else 0
        )
        hits = [
            SearchHit(**c.model_dump(), score=s, rank=i)
            for i, (s, c) in enumerate(scored[:k], start=1)
        ]
        if not hits:
            return SearchResult(
                **base, status="not_found_in_scope", skipped_unverified_edition=skipped
            )
        return SearchResult(**base, skipped_unverified_edition=skipped, hits=hits)
