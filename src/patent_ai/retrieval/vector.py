"""벡터 검색 구현 (#66). impl 이름 vector. 말뭉치(law·cite)를 가리지 않는다.

- 점수: 질의 벡터와 조각 벡터의 코사인 유사도. 범위(고른 문서·기준일에 효력 있는 판) 안 조각만.
- 질의 벡터: 부르는 쪽이 넘긴 embed(글 → 벡터)를 쓴다. 없으면 설정 settings.query_vectors의
  기록 파일({질의: 벡터})을 읽는다 (채점기는 이 길로, 질의 벡터는 eval/retrieval/embed_queries가
  미리 만든다).
- 조각에 벡터가 없으면 조용히 빼지 않고 멈춘다 (색인을 잘못 고른 것).
- 점수 문턱은 두지 않는다. 범위 안 조각을 점수 순으로 k개까지.
core를 import하지 않는다 (모델 호출은 부르는 쪽 embed가 한다).
"""

from datetime import date

from patent_ai.retrieval.contract import Embed, register_impl
from patent_ai.retrieval.embedding import cosine, recorded_embed
from patent_ai.retrieval.errors import ModeNotSupportedError
from patent_ai.retrieval.repository import ChunkRepository
from patent_ai.retrieval.schemas import Corpus, Mode, SearchHit, SearchResult, SearchScope


@register_impl("vector")
class VectorSearcher:
    def __init__(self, repo: ChunkRepository, settings: dict, embed: Embed | None = None) -> None:
        self._repo = repo
        self._index_version: str = settings["index_version"]
        if embed is None and settings.get("query_vectors"):
            embed = recorded_embed(settings["query_vectors"])
        self._embed = embed

    def search(
        self,
        query: str,
        corpus: Corpus,
        mode: Mode,
        k: int,
        doc_ids: list[str] | None = None,
        as_of: date | None = None,
    ) -> SearchResult:
        if mode != "vector":
            raise ModeNotSupportedError(f"vector 구현은 vector 방식만 한다 (받은 값 {mode!r})")
        if self._embed is None:
            raise ValueError("vector 검색에는 embed(또는 settings['query_vectors'])가 필요하다")
        base = {
            "corpus": corpus,
            "index_version": self._index_version,
            "mode": mode,
            "scope": SearchScope(doc_ids=doc_ids, as_of=as_of, k=k),
        }
        # 고른 문서에 조각이 하나도 없으면 본문이 없는 것
        if self._repo.count_chunks(corpus, self._index_version, doc_ids) == 0:
            return SearchResult(**base, status="unverified", status_reason="body_missing")
        skipped = (
            self._repo.count_unverified_edition(corpus, self._index_version, doc_ids)
            if as_of is not None
            else 0
        )

        qvec = self._embed(query)
        scored = []
        for chunk in self._repo.chunks(corpus, self._index_version, doc_ids, as_of):
            if chunk.embedding is None:
                raise ValueError(f"조각에 embedding이 없다: {chunk.chunk_id}")
            scored.append((cosine(qvec, chunk.embedding), chunk))
        # 점수 내림차순, 같으면 chunk_id 오름차순 (계약)
        scored.sort(key=lambda sc: (-sc[0], sc[1].chunk_id))

        hits = [
            SearchHit(**c.model_dump(), score=s, rank=i)
            for i, (s, c) in enumerate(scored[:k], start=1)
        ]
        if not hits:
            return SearchResult(
                **base, status="not_found_in_scope", skipped_unverified_edition=skipped
            )
        return SearchResult(**base, skipped_unverified_edition=skipped, hits=hits)
