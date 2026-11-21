"""BM25 검색 구현 (cite-search design 7-2절). 인용문헌·법령이 같이 쓴다.

검색 범위(doc_ids, 기준일 판) 조각만으로 bm25s 색인을 검색 때마다 만든다
(IDF가 그 범위 안에서 센다).
그래서 옛 판 법령 조각이 같이 있어도 idf가 흔들리지 않는다.
낱말 자르기는 settings.tokenizer(kiwi 기본 / char_bigram / whitespace)로 고른다.
core를 import하지 않는다. 모델 호출 없음.
"""

from datetime import date

import bm25s

from patent_ai.retrieval.contract import Embed, register_impl
from patent_ai.retrieval.errors import ModeNotSupportedError
from patent_ai.retrieval.repository import ChunkRepository
from patent_ai.retrieval.schemas import Corpus, Mode, SearchHit, SearchResult, SearchScope
from patent_ai.retrieval.tokenizer import make_tokenizer

# unique_query_terms: 질의에 같은 낱말이 여러 번 나와도 한 번만 센다 (Okapi 교과서 식).
# 기본 False는 bm25s 그대로(나온 만큼 셈)라 인용문헌 기준선 점수가 그대로 나온다.
_DEFAULTS = {"method": "lucene", "k1": 1.5, "b": 0.75, "unique_query_terms": False}


@register_impl("bm25")
class Bm25Searcher:
    def __init__(self, repo: ChunkRepository, settings: dict, embed: Embed | None = None) -> None:
        self._repo = repo
        self._index_version: str = settings["index_version"]
        self._tokenizer = make_tokenizer(
            settings.get("tokenizer", "kiwi"), settings.get("pos_tags")
        )
        bm25 = settings.get("bm25") or {}
        # 모르는 키(오타)를 조용히 버리면 기본값으로 채점된다. 막는다
        unknown = sorted(set(bm25) - set(_DEFAULTS))
        if unknown:
            raise ValueError(
                f"settings.bm25에 모르는 키 {unknown}. 쓸 수 있는 키: {list(_DEFAULTS)}"
            )
        # 옛 law_bm25 config는 k1·b를 settings 바로 아래에 뒀다. bm25 아래로 옮기라고 알린다
        for old in ("k1", "b"):
            if old in settings:
                raise ValueError(
                    f"settings.{old}는 옛 law_bm25 모양이다. settings.bm25.{old}로 옮긴다"
                )
        self._bm25 = {**_DEFAULTS, **bm25}
        if not isinstance(self._bm25["unique_query_terms"], bool):
            raise ValueError("bm25.unique_query_terms는 true/false만 쓴다")
        # 조각 글을 질의마다 다시 분석하지 않게 chunk_id별로 기억한다
        self._token_cache: dict[str, list[str]] = {}

    def _tokens(self, chunk_id: str, text: str) -> list[str]:
        if chunk_id not in self._token_cache:
            self._token_cache[chunk_id] = self._tokenizer.tokenize(text)
        return self._token_cache[chunk_id]

    def search(
        self,
        query: str,
        corpus: Corpus,
        mode: Mode,
        k: int,
        doc_ids: list[str] | None = None,
        as_of: date | None = None,
    ) -> SearchResult:
        if mode != "bm25":
            raise ModeNotSupportedError(f"bm25 구현은 mode={mode!r}를 지원하지 않는다")
        base = {
            "corpus": corpus,
            "index_version": self._index_version,
            "mode": mode,
            "scope": SearchScope(doc_ids=doc_ids, as_of=as_of, k=k),
        }
        # 문헌 조각이 0개면 본문이 없는 것
        if self._repo.count_chunks(corpus, self._index_version, doc_ids) == 0:
            return SearchResult(**base, status="unverified", status_reason="body_missing")

        chunks = self._repo.chunks(corpus, self._index_version, doc_ids, as_of)
        skipped = (
            self._repo.count_unverified_edition(corpus, self._index_version, doc_ids)
            if as_of is not None
            else 0
        )
        q_tokens = self._tokenizer.tokenize(query)
        if self._bm25["unique_query_terms"]:
            # 긴 질의(법령 거절이유 본문)에서 흔한 낱말이 반복돼 점수를 끌고 가지 않게
            # 처음 나온 순서로 한 번씩만 남긴다
            q_tokens = list(dict.fromkeys(q_tokens))
        doc_tokens = [self._tokens(c.chunk_id, c.text) for c in chunks]

        scores: list[float] = [0.0] * len(chunks)
        # 질의나 조각 글이 전부 빈 토큰이면 bm25s가 색인을 못 만든다. 그땐 점수 0으로 둔다
        if q_tokens and any(doc_tokens):
            retriever = bm25s.BM25(
                method=self._bm25["method"], k1=self._bm25["k1"], b=self._bm25["b"]
            )
            retriever.index(doc_tokens, show_progress=False)
            scores = [float(s) for s in retriever.get_scores(q_tokens)]

        # 점수 내림차순, 같으면 chunk_id 오름차순. 0점 이하는 뺀다
        ranked = sorted(
            ((s, c) for s, c in zip(scores, chunks, strict=True) if s > 0),
            key=lambda sc: (-sc[0], sc[1].chunk_id),
        )
        hits = [
            SearchHit(**c.model_dump(), score=s, rank=i)
            for i, (s, c) in enumerate(ranked[:k], start=1)
        ]
        if not hits:
            return SearchResult(
                **base, status="not_found_in_scope", skipped_unverified_edition=skipped
            )
        return SearchResult(**base, skipped_unverified_edition=skipped, hits=hits)
