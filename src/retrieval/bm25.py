"""BM25 검색기 (M1/M2). 토크나이저를 바꿔 끼워 비교한다.

- 점수가 0인 청크(질문과 겹치는 토큰이 없음)는 순위에 넣지 않는다. 0점끼리의 순서는
  의미가 없어서, 넣으면 정답이 우연히 순위에 들어와 보일 수 있다.
- 점수가 같으면 청크 입력 순서(원래 파일 순서)를 따른다. 같은 입력이면 항상 같은 순위.
"""
from typing import Callable

from rank_bm25 import BM25Okapi

Tokenizer = Callable[[str], list[str]]


def whitespace_tokenizer(text: str) -> list[str]:
    """공백 기준 분리(M1 기준선). 조사가 붙은 말은 그대로 한 토큰이다."""
    return text.split()


class Bm25Retriever:
    def __init__(self, chunks: list[dict], tokenizer: Tokenizer = whitespace_tokenizer,
                 text_key: str = "text"):
        self._ids = [c["chunk_id"] for c in chunks]
        self._tokenizer = tokenizer
        self._bm25 = BM25Okapi([tokenizer(c[text_key]) for c in chunks])

    def search(self, query: str, top_n: int = 20) -> list[tuple[str, float]]:
        """(chunk_id, 점수) 목록, 점수 높은 순. 점수 0 이하는 제외."""
        scores = self._bm25.get_scores(self._tokenizer(query))
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
        return [(self._ids[i], float(scores[i])) for i in order if scores[i] > 0][:top_n]
