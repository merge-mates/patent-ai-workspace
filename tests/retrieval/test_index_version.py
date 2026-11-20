"""색인 판 이름 `<말뭉치>-idx-v<N>` 풀기 (PR #163 리뷰: 세 곳에 따로 있던 규칙을 하나로)."""

import pytest

from patent_ai.retrieval.index_version import corpus_of, is_index_version


@pytest.mark.parametrize(
    ("corpus", "v", "ok"),
    [
        ("law", "law-idx-v1", True),
        ("cite", "cite-idx-v12", True),
        ("law", "cite-idx-v1", False),  # 말뭉치가 다름
        ("cite", "cite-idx-v", False),  # 번호 없음
        ("cite", "cite-idx-v2x", False),  # 꼬리 붙음
        ("cite", "xcite-idx-v2", False),  # 앞에 붙음
        ("law", "law-idx-1", False),
    ],
)
def test_is_index_version(corpus, v, ok):
    assert is_index_version(corpus, v) is ok


@pytest.mark.parametrize(
    ("v", "corpus"),
    [
        ("law-idx-v2", "law"),
        ("cite-idx-v2", "cite"),
        ("case-idx-v1", None),
        ("cite", None),
        ("", None),
    ],
)
def test_corpus_of(v, corpus):
    assert corpus_of(v) == corpus
