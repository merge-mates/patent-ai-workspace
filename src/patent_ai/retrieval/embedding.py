"""벡터 검색 공용 도구: 코사인 유사도와 기록된 {질의: 벡터} 파일 읽기 (fake·vector가 같이 씀).

core를 import하지 않는다 (진짜 임베딩은 부르는 쪽이 core/llm embed로 넘긴다).
"""

import json
import math
from pathlib import Path

from patent_ai.retrieval.contract import Embed
from patent_ai.retrieval.errors import RecordedEmbeddingMissing


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"벡터 차원이 다르다: {len(a)} != {len(b)}")
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0  # 길이 0 벡터는 비슷함을 말할 수 없다
    return sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb)


def recorded_embed(path: str | Path) -> Embed:
    """녹화해 둔 {질의: 벡터} 파일을 읽는 embed. 실제 모델을 부르지 않는다."""
    with open(path, encoding="utf-8") as f:
        recorded: dict[str, list[float]] = json.load(f)

    def embed(query: str) -> list[float]:
        if query not in recorded:
            raise RecordedEmbeddingMissing(f"녹화에 없는 질의: {query!r}")
        return recorded[query]

    return embed
