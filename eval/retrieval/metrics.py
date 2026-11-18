"""Hit@k·Recall@k·무작위 기준선 계산식 (design: docs/features/retrieval/design.md 7-3).

모두 순수 함수다. 조각이 정답 항목에 맞는지는 Matcher가 정하고, 여기는 숫자만 계산한다.
"""

from math import comb


def _check_k(k: int) -> None:
    if k < 1:
        raise ValueError(f"k는 1 이상이어야 한다: {k}")


def _check_n(n: int) -> None:
    # 검색 범위 조각이 0개인 줄은 그 전에 점수에서 빠져야 한다
    if n < 1:
        raise ValueError(f"검색 범위 조각 수 N은 1 이상이어야 한다: {n}")


def row_hit(matched_items_by_rank: list[set[int]], k: int) -> int:
    """상위 k개 안에 어느 항목이든 맞은 조각이 있으면 1, 없으면 0.

    matched_items_by_rank[i] = 순위 i 조각이 맞힌 항목 번호 집합.
    """
    _check_k(k)
    return int(any(matched_items_by_rank[:k]))


def row_recall(matched_items_by_rank: list[set[int]], n_items: int, k: int) -> float:
    """맞은 항목 수 / 항목 수. 같은 항목을 여러 조각이 맞혀도 한 번만 센다."""
    _check_k(k)
    if n_items < 1:
        raise ValueError(f"항목 수는 1 이상이어야 한다: {n_items}")
    found: set[int] = set()
    for items in matched_items_by_rank[:k]:
        found |= items
    return len(found) / n_items


def _p_at_least_one(n: int, matched: int, k: int) -> float:
    """N개 중 k'개를 고르게 뽑을 때, 맞는 조각 matched개 중 하나라도 뽑힐 확률."""
    k_eff = min(k, n)  # N이 k보다 작으면 전부 뽑는 것과 같다
    if matched <= 0:
        return 0.0
    return 1 - comb(n - matched, k_eff) / comb(n, k_eff)


def random_recall(n: int, match_sizes: list[int], k: int) -> float:
    """무작위로 k'개 뽑았을 때 기대 Recall: 항목별 확률의 평균.

    match_sizes[i] = 항목 i에 맞는 조각 수 |Mi|.
    """
    _check_n(n)
    _check_k(k)
    if not match_sizes:
        raise ValueError("항목이 하나도 없다")
    return sum(_p_at_least_one(n, m, k) for m in match_sizes) / len(match_sizes)


def random_hit(n: int, union_size: int, k: int) -> float:
    """무작위로 k'개 뽑았을 때 기대 Hit: union_size = 어느 항목에든 맞는 조각 수 |∪Mi|."""
    _check_n(n)
    _check_k(k)
    return _p_at_least_one(n, union_size, k)
