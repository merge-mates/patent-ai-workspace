"""fake 검색 구현 (design.md 7-2절). 실제 모델·DB 없이 계약을 시험하는 용도.

- bm25: 질의 낱말(공백으로 자름)이 조각 낱말과 겹치는 수
- vector: embed(질의)와 조각 벡터의 코사인 유사도. 테스트는 녹화 파일을 읽는 embed를 쓴다
core를 import하지 않는다.
"""

from datetime import date

from patent_ai.retrieval.contract import Embed, register_impl
from patent_ai.retrieval.embedding import cosine, recorded_embed
from patent_ai.retrieval.errors import ModeNotSupportedError
from patent_ai.retrieval.repository import ChunkRepository
from patent_ai.retrieval.schemas import (
    Chunk,
    ChunkKind,
    Corpus,
    Mode,
    SearchHit,
    SearchResult,
    SearchScope,
    SourceKind,
)


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
        return cosine(qvec, chunk.embedding)

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
        # fake는 bm25·vector만 한다. hybrid는 hybrid impl이 섞는다 (래퍼가 더는 막지 않음)
        if mode not in ("bm25", "vector"):
            raise ModeNotSupportedError(f"fake 구현은 bm25·vector만 한다 (받은 값 {mode!r})")
        scope = SearchScope(
            doc_ids=doc_ids,
            as_of=as_of,
            k=k,
            chunk_kinds=chunk_kinds,
            source_kinds=source_kinds,
            decided_on_or_before=decided_on_or_before,
        )
        # 거르기 인자 묶음: 저장소 조회·세기에 같은 범위를 쓴다
        flt = {"chunk_kinds": chunk_kinds, "source_kinds": source_kinds}
        base = {
            "corpus": corpus,
            "index_version": self._index_version,
            "mode": mode,
            "scope": scope,
        }
        qvec = self._query_vector(query) if mode == "vector" else None

        # 문헌·자료 유형으로 거른 조각이 0개면 본문이 없는 것 (기준일·선고일과 상관없이)
        if self._repo.count_chunks(corpus, self._index_version, doc_ids, **flt) == 0:
            return SearchResult(**base, status="unverified", status_reason="body_missing")

        chunks = self._repo.chunks(
            corpus,
            self._index_version,
            doc_ids,
            as_of,
            decided_on_or_before=decided_on_or_before,
            **flt,
        )
        scored = [(self._score(c, mode, query, qvec), c) for c in chunks]
        # 점수 0 이하는 뺀다. 점수 내림차순, 같으면 chunk_id 오름차순
        scored = [(s, c) for s, c in scored if s > 0]
        scored.sort(key=lambda sc: (-sc[0], sc[1].chunk_id))

        # 기준일 검색에서 판본을 몰라 빠진 조각 수
        skipped = (
            self._repo.count_unverified_edition(
                corpus,
                self._index_version,
                doc_ids,
                decided_on_or_before=decided_on_or_before,
                **flt,
            )
            if as_of is not None
            else 0
        )
        # 선고일 거르기를 걸었을 때 선고일 모름으로 빠진 판례·심결 수
        unknown_date = (
            self._repo.count_unknown_date(corpus, self._index_version, doc_ids, **flt)
            if decided_on_or_before is not None
            else 0
        )
        extra = {"skipped_unverified_edition": skipped, "skipped_unknown_date": unknown_date}
        hits = [
            SearchHit(**c.model_dump(), score=s, rank=i)
            for i, (s, c) in enumerate(scored[:k], start=1)
        ]
        if not hits:
            return SearchResult(**base, status="not_found_in_scope", **extra)
        return SearchResult(**base, **extra, hits=hits)
