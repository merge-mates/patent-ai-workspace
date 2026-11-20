"""색인 판 이름 `<말뭉치>-idx-v<N>` 풀기 (PR #163 리뷰: 세 곳에 따로 있던 규칙을 하나로)."""

import pytest

from patent_ai.index_version import corpus_of, is_index_version, version_number


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


@pytest.mark.parametrize(
    ("corpus", "v", "n"),
    [
        ("cite", "cite-idx-v10", 10),
        ("law", "law-idx-v2", 2),
        ("law", "cite-idx-v2", None),  # 말뭉치가 다름
        ("cite", "cite-idx-v", None),
    ],
)
def test_version_number(corpus, v, n):
    # 덤프 이름은 가장 높은 판 번호로 정한다 (db/index_dump, 숫자로 비교 v10 > v9)
    assert version_number(corpus, v) == n


@pytest.mark.parametrize("module", ["patent_ai.index_version", "patent_ai.git_paths"])
def test_최상위_공통_모듈은_다른_패키지를_부르지_않는다(module):
    # db/·eval/도 쓰므로 retrieval·core·db·eval을 import하면 안 된다 (ADR 0003 부르는 방향)
    import ast
    import importlib
    from pathlib import Path

    m = importlib.import_module(module)
    tree = ast.parse(Path(m.__file__).read_text(encoding="utf-8"))
    names = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    names += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    banned = ("patent_ai.retrieval", "patent_ai.core", "patent_ai.db", "eval")
    assert not [x for x in names if x and x.startswith(banned)]


def test_말뭉치_목록이_검색_스키마와_같다():
    from typing import get_args

    from patent_ai.index_version import CORPORA
    from patent_ai.retrieval.schemas import Corpus

    assert CORPORA == get_args(Corpus)
