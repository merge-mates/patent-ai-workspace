"""법령 BM25 검색 구현 (#66). impl 이름 law_bm25.

- 점수: Okapi BM25. idf = ln((N - n + 0.5) / (n + 0.5) + 1),
  낱말 점수 = idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * 조각 길이 / 평균 길이)).
- N·n·평균 길이는 그 검색의 범위(고른 문서·기준일에 효력 있는 판) 안 조각으로 센다.
  그래서 옛 판 조각이 같이 있어도 idf가 흔들리지 않는다.
- 낱말 자르기(settings.tokenizer): char_bigram(기본, 공백 낱말을 두 글자씩 겹쳐) / whitespace.
- 값(k1, b, tokenizer)은 실험 설정 settings에서 읽는다. bm25 방식만 한다.
core를 import하지 않는다.
"""

import math
from collections import Counter
from datetime import date

from patent_ai.retrieval.contract import Embed, register_impl
from patent_ai.retrieval.errors import ModeNotSupportedError
from patent_ai.retrieval.repository import ChunkRepository
from patent_ai.retrieval.schemas import Corpus, Mode, SearchHit, SearchResult, SearchScope

TOKENIZERS = ("char_bigram", "whitespace")


def tokenize(text: str, how: str) -> list[str]:
    """글 → 낱말 목록. char_bigram은 '발명은' → ['발명', '명은'] (한 글자 낱말은 그대로)."""
    words = text.split()
    if how == "whitespace":
        return words
    if how == "char_bigram":
        # 조사가 붙어도('발명은'/'발명을') 앞 두 글자가 같이 걸리게
        return [w[i : i + 2] for w in words for i in range(max(len(w) - 1, 1))]
    raise ValueError(f"모르는 낱말 자르기 방식 {how!r}. 쓸 수 있는 것: {TOKENIZERS}")


@register_impl("law_bm25")
class LawBM25Searcher:
    def __init__(self, repo: ChunkRepository, settings: dict, embed: Embed | None = None) -> None:
        self._repo = repo
        self._index_version: str = settings["index_version"]
        self._tokenizer: str = settings.get("tokenizer", "char_bigram")
        if self._tokenizer not in TOKENIZERS:
            raise ValueError(
                f"모르는 낱말 자르기 방식 {self._tokenizer!r}. 쓸 수 있는 것: {TOKENIZERS}"
            )
        self._k1 = float(settings.get("k1", 1.5))
        self._b = float(settings.get("b", 0.75))
        # 조각 글은 바뀌지 않으므로 자른 결과를 chunk_id로 기억해 둔다 (질의마다 다시 안 자름)
        self._tf_cache: dict[str, tuple[Counter, int]] = {}

    def _doc_tf(self, chunk_id: str, text: str) -> tuple[Counter, int]:
        hit = self._tf_cache.get(chunk_id)
        if hit is None:
            toks = tokenize(text, self._tokenizer)
            hit = self._tf_cache[chunk_id] = (Counter(toks), len(toks))
        return hit

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
            raise ModeNotSupportedError(f"law_bm25는 bm25 방식만 한다 (받은 값 {mode!r})")
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

        chunks = self._repo.chunks(corpus, self._index_version, doc_ids, as_of)
        docs = [(c, *self._doc_tf(c.chunk_id, c.text)) for c in chunks]
        n_docs = len(docs)
        avg_len = sum(n for _, _, n in docs) / n_docs if n_docs else 0.0
        q_terms = set(tokenize(query, self._tokenizer))
        # 낱말마다 그 낱말이 든 조각 수(n) → idf
        df = Counter(t for _, tf, _ in docs for t in q_terms if t in tf)
        idf = {t: math.log((n_docs - n + 0.5) / (n + 0.5) + 1) for t, n in df.items()}

        scored = []
        for chunk, tf, length in docs:
            norm = self._k1 * (1 - self._b + self._b * length / avg_len) if avg_len else self._k1
            s = sum(idf[t] * tf[t] * (self._k1 + 1) / (tf[t] + norm) for t in q_terms if t in tf)
            if s > 0:  # 겹치는 낱말이 없는 조각은 후보가 아니다
                scored.append((s, chunk))
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
