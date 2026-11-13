"""밀집(임베딩) 검색기 (M3). 미리 만든 벡터 파일(scripts/embed_openai.py 결과)을 읽어 코사인 유사도로 순위를 낸다.

- 질문 벡터는 질문 문장을 키로 찾는다(API 호출 없음).
- BM25 와 달리 모든 청크에 점수가 있어 항상 top_n 개가 나온다. 동점은 입력 순서.
"""
import json
from pathlib import Path

import numpy as np


def load_embeddings(path: Path) -> tuple[dict, list[str], np.ndarray]:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return d["meta"], d["ids"], np.asarray(d["vectors"], dtype=np.float64)


def _normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=-1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("영벡터가 있습니다.")
    return m / norms


class DenseRetriever:
    def __init__(self, chunk_ids: list[str], chunk_vectors: np.ndarray,
                 query_vectors: dict[str, np.ndarray]):
        if len(chunk_ids) != len(chunk_vectors):
            raise ValueError("청크 id 와 벡터 개수가 다릅니다.")
        self._ids = list(chunk_ids)
        self._m = _normalize(np.asarray(chunk_vectors, dtype=np.float64))
        self._q = {k: _normalize(np.asarray(v, dtype=np.float64)) for k, v in query_vectors.items()}

    def search(self, query: str, top_n: int = 20) -> list[tuple[str, float]]:
        if query not in self._q:
            raise KeyError(f"질문 벡터가 없습니다: {query!r}")
        scores = self._m @ self._q[query]
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))[:top_n]
        return [(self._ids[i], float(scores[i])) for i in order]
