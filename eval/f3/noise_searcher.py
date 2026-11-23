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

import logging
from collections.abc import Sequence
from pathlib import Path

from eval.retrieval.errors import RetrievalEvalError
from eval.retrieval.gold import GoldRow
from eval.retrieval.noise_scope import load_noise_scope

logger = logging.getLogger(__name__)


class NoiseScopedSearcher:
    """`Searcher`와 같은 모양. `doc_ids`에 노이즈 문헌을 덧붙여 안쪽 검색기에 넘긴다."""

    def __init__(self, inner, scope: dict[str, list[str]]) -> None:
        self._inner = inner
        self._scope = scope  # 인용문헌 doc_id -> 노이즈 문헌 doc_id 목록
        # 범위에 없어 넓히지 못한 인용문헌 doc_id -> 검색 수 (실험 카드에 적는다.
        # 넓히지 못한 검색은 주 점수 범위와 같아지므로 조용히 섞이지 않게 센다)
        self.unwidened: dict[str, int] = {}

    def search(self, query, corpus, mode, k, doc_ids=None, as_of=None, **kw):
        return self._inner.search(
            query, corpus, mode, k, doc_ids=self._widen(doc_ids), as_of=as_of, **kw
        )

    def _widen(self, doc_ids: list[str] | None) -> list[str] | None:
        if doc_ids is None:
            return None  # 범위 제한이 없는 검색은 건드리지 않는다
        out: list[str] = []
        for d in doc_ids:
            if d not in self._scope:
                if d not in self.unwidened:
                    # 문헌 ID는 로그에 찍지 않는다 (수만)
                    logger.warning(
                        "노이즈 범위에 없는 인용문헌이 있어 그 검색은 넓히지 못함 (지금 %d개)",
                        len(self.unwidened) + 1,
                    )
                self.unwidened[d] = self.unwidened.get(d, 0) + 1
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
    if not gold_rows:
        # 정답 줄이 없으면 모든 검색이 주 점수 범위가 된다. 조용히 넘기지 않는다
        raise RetrievalEvalError("노이즈 범위를 만들 정답 줄이 0개다")
    by_row = load_noise_scope(path)
    out: dict[str, list[str]] = {}
    oa_of: dict[str, str] = {}  # 인용문헌 doc_id -> 처음 본 OA (row_id 첫 칸 = 발송번호)
    for row in gold_rows:
        oa = row.row_id.split(":", 1)[0]
        for doc in row.doc_ids or []:
            # search-gold 5절: 노이즈는 그 OA 줄 범위에만. 한 문헌이 OA 둘에 걸치면
            # 다른 OA의 노이즈가 섞이므로 멈춘다 (실험 스크립트가 OA마다 따로 감싼다)
            if oa_of.setdefault(doc, oa) != oa:
                raise RetrievalEvalError(
                    "한 인용문헌이 OA 둘 이상의 정답 줄에 있다: OA마다 따로 감싼다"
                )
        if row.row_id not in by_row:
            raise RetrievalEvalError(f"노이즈 범위 파일에 줄이 없다: {row.row_id}")
        gold_docs = set(row.doc_ids or [])
        noise = [d for d in by_row[row.row_id] if d not in gold_docs]
        for doc in row.doc_ids or []:
            merged = out.setdefault(doc, [])
            merged.extend(d for d in noise if d not in merged)
    return out
