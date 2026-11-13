import numpy as np
import pytest

from src.retrieval.dense import DenseRetriever


def make():
    ids = ["법#제1조", "법#제2조", "법#제3조"]
    vecs = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    return DenseRetriever(ids, vecs, {"q1": np.array([2.0, 0.0]), "q2": np.array([1.0, 1.0])})


def test_cosine_ranking_ignores_vector_length():
    r = make()
    assert [c for c, _ in r.search("q1")] == ["법#제1조", "법#제3조", "법#제2조"]
    top = r.search("q1")[0]
    assert top[1] == pytest.approx(1.0)


def test_ties_follow_input_order():
    r = make()
    # q2 는 제1조·제2조와 점수가 같고 제3조와는 완전 일치
    ranked = [c for c, _ in r.search("q2")]
    assert ranked == ["법#제3조", "법#제1조", "법#제2조"]


def test_top_n_and_missing_query_and_zero_vector():
    r = make()
    assert len(r.search("q1", top_n=2)) == 2
    with pytest.raises(KeyError):
        r.search("없는 질문")
    with pytest.raises(ValueError):
        DenseRetriever(["a"], np.array([[0.0, 0.0]]), {})
    with pytest.raises(ValueError):
        DenseRetriever(["a", "b"], np.array([[1.0, 0.0]]), {})


def test_negative_cosine_ranks_last():
    r = DenseRetriever(["a", "b", "c"], np.array([[1.0, 0.0], [-1.0, 0.0], [0.0, 1.0]]),
                       {"q": np.array([1.0, 0.0])})
    out = r.search("q")
    assert [c for c, _ in out] == ["a", "c", "b"]
    assert out[-1][1] == pytest.approx(-1.0)
