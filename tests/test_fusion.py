import pytest

from src.retrieval.fusion import HybridRetriever, rrf


def test_rrf_hand_computed_scores():
    out = dict(rrf([["a", "b", "c"], ["b", "a", "d"]], k=60))
    assert out["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert out["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert out["c"] == pytest.approx(1 / 63)
    assert out["d"] == pytest.approx(1 / 63)


def test_item_in_both_lists_beats_item_high_in_one():
    ranked = [c for c, _ in rrf([["x", "a"], ["y", "a"]])]
    assert ranked[0] == "a"  # 2위+2위 > 1위 하나


def test_ties_prefer_first_seen_and_are_deterministic():
    r1 = rrf([["a", "b"], ["b", "a"]])
    assert [c for c, _ in r1] == ["a", "b"]  # 점수 동일 -> 먼저 등장한 a
    assert r1 == rrf([["a", "b"], ["b", "a"]])
    # c 와 d 는 서로 다른 목록의 같은 순위 -> 앞쪽 목록의 c 가 먼저
    assert [c for c, _ in rrf([["c"], ["d"]])] == ["c", "d"]


def test_empty_and_single_list():
    assert rrf([]) == []
    assert [c for c, _ in rrf([["a", "b"]])] == ["a", "b"]


class Fake:
    def __init__(self, ids):
        self.ids, self.calls = ids, []

    def search(self, query, top_n=20):
        self.calls.append(top_n)
        return [(i, 1.0) for i in self.ids][:top_n]


def test_hybrid_uses_depth_and_limits_top_n():
    a, b = Fake(["법#제1조", "법#제2조", "법#제3조"]), Fake(["법#제3조", "법#제2조", "법#제4조"])
    h = HybridRetriever([a, b], depth=50)
    out = h.search("q", top_n=2)
    assert a.calls == [50] and b.calls == [50]
    # z = 1/63 + 1/61 = 0.032266 > y = 1/62 + 1/62 = 0.032258 (손으로 계산)
    assert [c for c, _ in out] == ["법#제3조", "법#제2조"]


class Scored:
    """점수와 순서가 일부러 어긋난 검색기: 하이브리드는 점수가 아니라 돌려준 순서를 써야 한다."""

    def __init__(self, pairs):
        self.pairs = pairs

    def search(self, query, top_n=20):
        return self.pairs[:top_n]


def test_hybrid_uses_returned_order_not_scores_and_handles_short_lists():
    a = Scored([("법#제1조", 0.1), ("법#제2조", 9.9)])  # 점수는 y가 높지만 순서는 x가 먼저
    b = Scored([("법#제1조", 0.0)])  # depth 보다 짧게 돌려주는 검색기
    out = HybridRetriever([a, b]).search("q")
    assert [c for c, _ in out] == ["법#제1조", "법#제2조"]
    assert out[0][1] == pytest.approx(1 / 61 + 1 / 61)


def test_collapse_to_articles_keeps_first_position_per_article():
    from src.retrieval.fusion import collapse_to_articles
    ids = ["법#제2조#제1항", "법#제1조", "법#제2조#제3항", "법#제2조", "법#제3조#제2항"]
    assert collapse_to_articles(ids) == ["법#제2조", "법#제1조", "법#제3조"]


def test_hybrid_merges_paragraph_and_article_chunks_of_same_article():
    a = Fake(["법#제5조#제1항", "법#제6조"])
    b = Fake(["법#제6조", "법#제5조"])
    out = HybridRetriever([a, b]).search("q")
    # 5조: 1/61+1/62, 6조: 1/62+1/61 -> 동점, 먼저 나온 5조가 앞
    assert [c for c, _ in out] == ["법#제5조", "법#제6조"]
    assert out[0][1] == pytest.approx(1 / 61 + 1 / 62)


def test_hybrid_rrf_uses_collapsed_positions():
    a = Fake(["법#제5조#제1항", "법#제5조#제2항", "법#제6조"])
    out = HybridRetriever([a, Fake([])]).search("q")
    assert [c for c, _ in out] == ["법#제5조", "법#제6조"]
    assert out[1][1] == pytest.approx(1 / 62)  # 묶은 뒤 2번째, 청크 기준이면 1/63


def test_hybrid_equals_chunk_level_rrf_on_article_only_lists():
    from src.retrieval.fusion import rrf
    la = ["법#제1조", "법#제2조", "법#제3조"]
    lb = ["법#제3조", "법#제1조"]
    got = HybridRetriever([Fake(la), Fake(lb)]).search("q")
    assert got == rrf([la, lb], 60)[:20]
