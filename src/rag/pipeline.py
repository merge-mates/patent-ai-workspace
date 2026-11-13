"""검색 파이프라인(Phase 6 확정 후보): 확장 v2 → 임베딩 → BM25+임베딩 RRF(M4a) → 상위 10개 LLM 재순위 → 앞 5개를 근거로.

외부 호출(확장·질의 임베딩·재순위)은 함수로 주입받아 테스트에서 가짜로 바꿀 수 있다. build_pipeline 이 실제 함수를 연결한다.
이전에 만든 간단한 챗봇 실습 코드의 검색 부분과 같은 모양으로 새로 썼다(복사하지 않음).
"""
import json
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from src.rag.evidence import Evidence, build_evidence
from src.rag.settings import Settings, load_key
from src.retrieval.bm25 import Bm25Retriever
from src.retrieval.dense import load_embeddings
from src.retrieval.fusion import HybridRetriever
from src.retrieval.llm_rerank import article_texts, llm_rerank
from src.retrieval.openai_embed import embed_texts
from src.retrieval.query_expand import expand_one, expanded_query, parse_terms
from src.retrieval import usage
from src.retrieval.tokenizers import kiwi_tokenizer

ARTICLE_DEPTH = 20  # M4a 가 돌려주는 조문 순위 길이(평가와 같은 컷오프)


@dataclass
class Retrieval:
    question: str
    query: str              # 확장된 검색어(질문 + 법률 용어)
    expansion_raw: str      # 확장 모델 원문 응답
    terms: list[str]
    ranked: list[str]       # 재순위된 앞 rerank_window 개 조문 id
    rerank_raw: str         # 재순위 모델 원문 응답
    evidence: list[Evidence]
    usage: dict = field(default_factory=dict)  # 검색 단계(확장·임베딩·재순위) 토큰 사용량 요약, 예전 캐시에는 없다


class LiveDenseRetriever:
    """질문 벡터를 즉석에서 계산하는 밀집 검색기(DenseRetriever 와 같은 코사인 순위, 동점은 입력 순서)."""

    def __init__(self, chunk_ids: list[str], chunk_matrix: np.ndarray, embed_query: Callable[[str], list[float]]):
        m = np.asarray(chunk_matrix, dtype=np.float64)
        norms = np.linalg.norm(m, axis=-1, keepdims=True)
        if np.any(norms == 0):
            raise ValueError("영벡터가 있습니다.")
        self._ids, self._m, self._embed = list(chunk_ids), m / norms, embed_query

    def search(self, query: str, top_n: int = 20) -> list[tuple[str, float]]:
        v = np.asarray(self._embed(query), dtype=np.float64)
        scores = self._m @ (v / np.linalg.norm(v))
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))[:top_n]
        return [(self._ids[i], float(scores[i])) for i in order]


class Pipeline:
    def __init__(self, settings: Settings, chunks: list[dict], chunk_ids: list[str], chunk_matrix: np.ndarray,
                 expand: Callable[[str], str], embed_query: Callable[[str], list[float]],
                 rerank: Callable[[str, list[str]], tuple[list[str], str]], tokenizer=kiwi_tokenizer):
        self._s, self._expand, self._rerank = settings, expand, rerank
        self._texts = article_texts(chunks, max_chars=10 ** 6)  # 전문을 한 번만 만든다(잘림은 build_evidence 가 담당)
        self._hybrid = HybridRetriever([Bm25Retriever(chunks, tokenizer=tokenizer),
                                        LiveDenseRetriever(chunk_ids, chunk_matrix, embed_query)])

    def retrieve(self, question: str) -> Retrieval:
        if not question.strip():
            raise ValueError("질문이 비어 있습니다.")  # 외부 호출 전에 막는다
        with usage.capture() as recs:  # 이 검색에서 일어난 확장·임베딩·재순위 호출의 토큰 사용량을 모은다
            raw = self._expand(question)
            terms = parse_terms(raw)
            query = expanded_query(question, terms)
            ranked = [a for a, _ in self._hybrid.search(query, top_n=ARTICLE_DEPTH)]
            reranked, rerank_raw = self._rerank(question, ranked)  # 재순위에는 원 질문(확장 전)을 쓴다
        evidence = build_evidence(reranked, self._texts, self._s.n_evidence, self._s.max_evidence_chars)
        return Retrieval(question, query, raw, terms, reranked[:self._s.rerank_window], rerank_raw, evidence,
                         usage.summarize(recs))


def build_pipeline(settings: Settings) -> Pipeline:
    """코퍼스·청크 임베딩을 읽고 실제 OpenAI 호출 함수를 연결한다. 청크 id 순서가 어긋나면 RuntimeError."""
    chunks = [json.loads(l) for l in settings.corpus.read_text(encoding="utf-8").splitlines() if l.strip()]
    meta, ids, matrix = load_embeddings(settings.chunk_emb)
    if ids != [c["chunk_id"] for c in chunks]:
        raise RuntimeError("벡터 파일의 청크 id 가 코퍼스와 다릅니다(순서 포함). 임베딩을 다시 만드세요.")
    key = load_key("OPENAI_API_KEY", settings.env_path)
    rerank_texts = article_texts(chunks)  # 재순위 프롬프트는 Phase 6 에서 잰 대로 조문당 1,500자까지만 보여 준다
    return Pipeline(
        settings, chunks, ids, matrix,
        expand=lambda q: expand_one(q, settings.expand_model, key, version="v2"),
        embed_query=lambda q: embed_texts([q], meta["model"], key)[0],
        rerank=lambda q, ranked: llm_rerank(q, ranked, rerank_texts, settings.rerank_model, key, window=settings.rerank_window),
    )
