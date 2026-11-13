"""하이브리드 검색(M4): 여러 검색기의 순위를 Reciprocal Rank Fusion(RRF)으로 합친다.

조문 단위로 합친다: 각 검색기의 순위를 먼저 **조문 단위로 묶고**(같은 조문의 청크는 가장 높은 순위 하나만) 그 조문 id 로 RRF 를 한다.
항 단위 청크("법#제29조#제1항")와 조문 청크("법#제29조")가 섞여도 같은 조문이면 점수가 합쳐진다. 조문 청크만 있는 코퍼스에서는 청크 단위와 결과가 같다.
점수 = 각 검색기에서의 순위 r 에 대해 합계 1 / (k + r), r 은 1부터. 해당 순위 목록에 없으면 0.
가중치는 두지 않는다(질문 12개에 맞춰 조정하는 것을 막기 위해). k=60 고정(RRF 원 논문의 관례값).
동점이면 먼저 등장한 청크(앞쪽 검색기·높은 순위 우선)가 앞선다. 같은 입력이면 항상 같은 결과.
"""
from typing import Protocol

from src.eval.metrics import article_of

K = 60
DEPTH = 100  # 각 검색기에서 가져오는 순위 깊이


class _Searcher(Protocol):
    def search(self, query: str, top_n: int = ...) -> list[tuple[str, float]]: ...


def collapse_to_articles(chunk_ids: list[str]) -> list[str]:
    """청크 id 순위 -> 조문 id 순위(같은 조문은 처음 나온 위치만 남김)."""
    seen: dict[str, None] = {}
    for cid in chunk_ids:
        seen.setdefault(article_of(cid), None)
    return list(seen)


def rrf(rankings: list[list[str]], k: int = K) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for pos, cid in enumerate(ranking, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + pos)
    first_seen = {cid: i for i, cid in enumerate(scores)}  # dict 는 삽입 순서 유지
    return sorted(scores.items(), key=lambda kv: (-kv[1], first_seen[kv[0]]))


class HybridRetriever:
    def __init__(self, retrievers: list[_Searcher], k: int = K, depth: int = DEPTH):
        self._rs, self._k, self._depth = retrievers, k, depth

    def search(self, query: str, top_n: int = 20) -> list[tuple[str, float]]:
        rankings = [collapse_to_articles([cid for cid, _ in r.search(query, top_n=self._depth)])
                    for r in self._rs]
        return rrf(rankings, self._k)[:top_n]
