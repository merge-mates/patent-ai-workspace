"""공통 검사 래퍼 테스트. 기대값은 design.md 7-1절 검사 목록에서 가져온다."""

import pytest

from patent_ai.retrieval import (
    IndexVersionMismatchError,
    ModeNotSupportedError,
    SearchContractViolationError,
    UnknownImplError,
    UnknownIndexVersionError,
    get_searcher,
    register_impl,
)
from patent_ai.retrieval.schemas import Chunk, SearchHit, SearchResult, SearchScope

IV = "cite-idx-v1"


class FakeRepo:
    def has_index_version(self, corpus, index_version):
        return (corpus, index_version) == ("cite", IV)


def _hit(chunk_id, score, rank, index_version=IV):
    c = Chunk(
        chunk_id=chunk_id,
        index_version=index_version,
        doc_id="D1",
        chunk_kind="body",
        location={"kind": "paragraph", "start": 1, "end": 1, "label": "[0001]"},
        edition={"status": "not_applicable"},
        text="t",
    )
    return SearchHit(**c.model_dump(), score=score, rank=rank)


def _result(hits, k=5):
    return SearchResult(
        corpus="cite",
        index_version=IV,
        mode="bm25",
        scope=SearchScope(k=k),
        status=None if hits else "not_found_in_scope",
        hits=hits,
    )


def _register(name, hits_fn):
    @register_impl(name)
    class _Impl:
        def __init__(self, repo, settings):
            pass

        def search(self, query, corpus, mode, k, doc_ids=None, as_of=None):
            return _result(hits_fn(), k)

    return _Impl


def _get(name="t"):
    return get_searcher(name, FakeRepo(), {"index_version": IV})


def _search(s, **kw):
    args = dict(query="q", corpus="cite", mode="bm25", k=5)
    args.update(kw)
    return s.search(**args)


def test_이름으로_고르고_정상_결과는_그대로_통과():
    hits = [_hit("a", 2.0, 1), _hit("b", 1.0, 2)]
    _register("t", lambda: hits)
    r = _search(_get())
    assert [h.chunk_id for h in r.hits] == ["a", "b"]


def test_같은_점수는_chunk_id_오름차순이면_통과():
    _register("t", lambda: [_hit("a", 1.0, 1), _hit("b", 1.0, 2)])
    assert len(_search(_get()).hits) == 2


def test_없는_impl은_등록된_이름을_알려준다():
    _register("t", lambda: [])
    with pytest.raises(UnknownImplError, match="t"):
        get_searcher("nope", FakeRepo(), {"index_version": IV})


def test_settings에_index_version이_없으면_ValueError():
    _register("t", lambda: [])
    with pytest.raises(ValueError):
        get_searcher("t", FakeRepo(), {})


def test_k가_0이면_ValueError():
    _register("t", lambda: [])
    with pytest.raises(ValueError):
        _search(_get(), k=0)


def test_doc_ids가_빈_목록이면_ValueError():
    _register("t", lambda: [])
    with pytest.raises(ValueError):
        _search(_get(), doc_ids=[])


def test_모르는_corpus_mode_값은_ValueError():
    _register("t", lambda: [])
    with pytest.raises(ValueError):
        _search(_get(), corpus="x")
    with pytest.raises(ValueError):
        _search(_get(), mode="x")


def test_hybrid는_지원하지_않는다():
    _register("t", lambda: [])
    with pytest.raises(ModeNotSupportedError):
        _search(_get(), mode="hybrid")


def test_저장소에_없는_색인_판():
    _register("t", lambda: [])
    s = get_searcher("t", FakeRepo(), {"index_version": "cite-idx-v9"})
    with pytest.raises(UnknownIndexVersionError):
        _search(s)


def test_다른_색인_판_조각이_섞이면_오류():
    _register("t", lambda: [_hit("a", 2.0, 1), _hit("b", 1.0, 2, index_version="cite-idx-v2")])
    with pytest.raises(IndexVersionMismatchError):
        _search(_get())


def test_k보다_많이_돌려주면_오류():
    _register("t", lambda: [_hit("a", 3.0, 1), _hit("b", 2.0, 2), _hit("c", 1.0, 3)])
    with pytest.raises(SearchContractViolationError):
        _search(_get(), k=2)


def test_점수_순서가_틀리면_오류():
    _register("t", lambda: [_hit("a", 1.0, 1), _hit("b", 2.0, 2)])
    with pytest.raises(SearchContractViolationError):
        _search(_get())


def test_같은_점수인데_chunk_id_순서가_틀리면_오류():
    _register("t", lambda: [_hit("b", 1.0, 1), _hit("a", 1.0, 2)])
    with pytest.raises(SearchContractViolationError):
        _search(_get())
