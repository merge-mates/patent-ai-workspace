"""계산식 테스트. 기대값은 design.md 7-3 점검 예 (N=10, M1=4, M2=1, k=5)."""

import pytest

from eval.retrieval.metrics import random_hit, random_recall, row_hit, row_recall

# 상위 5개 중 3번째 조각만 항목 0(`[0022-0025]`)에 맞고, 항목 1(`도 3`)은 못 맞힘
TOP5_ONLY_ITEM0 = [set(), set(), {0}, set(), set()]


def test_random_recall_점검_예():
    assert random_recall(10, [4, 1], 5) == pytest.approx(0.738, abs=1e-3)


def test_random_hit_점검_예():
    assert random_hit(10, 5, 5) == pytest.approx(0.996, abs=1e-3)


def test_row_hit_점검_예():
    assert row_hit(TOP5_ONLY_ITEM0, 5) == 1


def test_row_recall_점검_예():
    assert row_recall(TOP5_ONLY_ITEM0, 2, 5) == pytest.approx(0.5, abs=1e-3)


def test_k_밖의_순위는_세지_않는다():
    ranks = [set(), set(), {0}]
    assert row_hit(ranks, 2) == 0
    assert row_recall(ranks, 2, 2) == 0


def test_맞은_조각이_없으면_hit_0():
    assert row_hit([set(), set()], 5) == 0


def test_같은_항목을_여러_조각이_맞혀도_한_번만_센다():
    assert row_recall([{0}, {0}, {1}], 2, 3) == pytest.approx(1.0)


def test_N이_k보다_작으면_k는_N으로():
    # 조각이 3개뿐이고 k=5면 3개를 전부 뽑는 것과 같다
    assert random_recall(3, [1], 5) == pytest.approx(1.0)
    assert random_hit(3, 1, 5) == pytest.approx(1.0)


def test_맞는_조각이_0개인_항목은_확률_0():
    # 항목 둘 중 하나는 확률 0.5(M=1, N=10, k=5), 하나는 0 → 평균 0.25
    assert random_recall(10, [1, 0], 5) == pytest.approx(0.25, abs=1e-3)
    assert random_hit(10, 0, 5) == pytest.approx(0.0)


def test_N이_0이면_오류():
    with pytest.raises(ValueError):
        random_recall(0, [1], 5)
    with pytest.raises(ValueError):
        random_hit(0, 0, 5)


def test_항목이_없으면_오류():
    with pytest.raises(ValueError):
        random_recall(10, [], 5)
    with pytest.raises(ValueError):
        row_recall([set()], 0, 5)


def test_k가_1보다_작으면_오류():
    with pytest.raises(ValueError):
        random_recall(10, [1], 0)
    with pytest.raises(ValueError):
        row_hit([set()], 0)
