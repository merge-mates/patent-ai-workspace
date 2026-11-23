"""노이즈 범위 검색기 감싸기 (이슈 #309, 둘째 점수).

F3 검색은 인용문헌 하나 안에서만 찾는다 (`doc_ids=[인용문헌]`, 주 점수).
둘째 점수는 거기에 다른 문헌(노이즈)을 섞은 범위에서 찾는다. 이 감싸기는 안쪽 검색기를
부르기 전에 `doc_ids`만 `[인용문헌, *노이즈 문헌]`으로 넓힌다. 다른 인자는 그대로 넘긴다.

범위 파일(`eval.retrieval.noise_scope`)은 정답 줄(row_id) 단위로 문헌 목록을 준다.
검색은 줄이 아니라 인용문헌 doc_id로 불리므로, 여기서 인용문헌별로 바꾼다.

노이즈 문헌을 정하는 규칙: 그 인용문헌이 정답 문헌인 줄들의 범위를 모아 합집합을 낸다.
  - 줄의 정답 문헌(`doc_ids`)은 노이즈가 아니라 빼고, 범위 파일의 나머지만 쓴다.
  - 범위 파일은 OA마다 만들어져 같은 OA의 줄은 노이즈가 거의 같다. 합집합이라 순서는
    범위 파일의 첫 등장 순이다.
정답 내용(위치)은 쓰지 않고 문헌 ID만 쓴다. 채점기 쪽이라 data/goldsets/ 파일을 읽어도 된다.
앱 코드(src/)는 바꾸지 않는다.
"""

from collections.abc import Sequence
from pathlib import Path

from eval.retrieval.errors import RetrievalEvalError
from eval.retrieval.gold import GoldRow
from eval.retrieval.noise_scope import load_noise_scope


class NoiseScopedSearcher:
    """`Searcher`와 같은 모양. `doc_ids`에 노이즈 문헌을 덧붙여 안쪽 검색기에 넘긴다."""

    def __init__(self, inner, scope: dict[str, list[str]]) -> None:
        self._inner = inner
        self._scope = scope  # 인용문헌 doc_id -> 노이즈 문헌 doc_id 목록

    def search(self, query, corpus, mode, k, doc_ids=None, as_of=None, **kw):
        return self._inner.search(
            query, corpus, mode, k, doc_ids=self._widen(doc_ids), as_of=as_of, **kw
        )

    def _widen(self, doc_ids: list[str] | None) -> list[str] | None:
        if doc_ids is None:
            return None  # 범위 제한이 없는 검색은 건드리지 않는다
        out: list[str] = []
        for d in doc_ids:
            # 인용문헌 먼저, 그다음 노이즈. 이미 든 문헌은 한 번만
            for x in [d, *self._scope.get(d, [])]:
                if x not in out:
                    out.append(x)
        return out


def load_doc_noise_scope(path: str | Path, gold_rows: Sequence[GoldRow]) -> dict[str, list[str]]:
    """범위 파일(줄 단위)을 인용문헌별 노이즈 문헌 목록으로 바꾼다.

    파일이 없거나 정답 줄이 파일에 없으면 RetrievalEvalError로 멈춘다
    (조용히 주 점수 범위로 가지 않는다).
    """
    by_row = load_noise_scope(path)
    out: dict[str, list[str]] = {}
    for row in gold_rows:
        if row.row_id not in by_row:
            raise RetrievalEvalError(f"노이즈 범위 파일에 줄이 없다: {row.row_id}")
        gold_docs = set(row.doc_ids or [])
        noise = [d for d in by_row[row.row_id] if d not in gold_docs]
        for doc in row.doc_ids or []:
            merged = out.setdefault(doc, [])
            merged.extend(d for d in noise if d not in merged)
    return out
