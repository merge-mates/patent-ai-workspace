"""공통 검사 래퍼 테스트. 기대값은 design.md 7-1절 검사 목록에서 가져온다."""

import pytest

from patent_ai.retrieval import (
    IndexVersionMismatchError,
    ModeNotSupportedError,
    SearchContractViolationError,
    UnknownImplError,
    UnknownIndexVersionError,
    contract,
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


class FakeRepoBoth(FakeRepo):
    def has_index_version(self, corpus, index_version):
        return index_version == IV


@pytest.fixture(autouse=True)
def _빈_등록표():
    # 테스트마다 같은 이름 "t"를 새로 등록하므로 등록표를 비워 준다.
    # conftest의 fixture는 저장·되돌리기만 해서 이 비우기가 따로 필요하다 (중복 등록 금지)
    contract._REGISTRY.clear()
    yield
    contract._REGISTRY.clear()


def _result(hits, k=5, index_version=IV, corpus="cite", mode="bm25"):
    return SearchResult(
        corpus=corpus,
        index_version=index_version,
        mode=mode,
        scope=SearchScope(k=k),
        status=None if hits else "not_found_in_scope",
        hits=hits,
    )


def _register(name, hits_fn, result_index_version=IV, override=None):
    # override: 결과 머리를 요청과 다르게 돌려줄 때 (corpus·mode·k)
    @register_impl(name)
    class _Impl:
        def __init__(self, repo, settings, embed):
            self.embed = embed

        def search(self, query, corpus, mode, k, doc_ids=None, as_of=None):
            head = {"k": k, "corpus": corpus, "mode": mode, **(override or {})}
            return _result(hits_fn(), index_version=result_index_version, **head)

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
    _register("impl_a", lambda: [])
    with pytest.raises(UnknownImplError, match=r"nope.*impl_a"):
        get_searcher("nope", FakeRepo(), {"index_version": IV})


def test_UnknownImplError는_이름_규칙을_알려준다():
    # law-bm25처럼 하이픈을 쓰면 import하지 않는다. 메시지로 이유를 알린다
    with pytest.raises(UnknownImplError, match=r"retrieval/<이름>\.py.*소문자·숫자·밑줄"):
        get_searcher("law-bm25", FakeRepo(), {"index_version": IV})


def test_embed는_구현에_그대로_넘어간다():
    impl = _register("t", lambda: [])

    def embed(q):
        return [0.0]

    s = get_searcher("t", FakeRepo(), {"index_version": IV}, embed=embed)
    assert isinstance(s._inner, impl)
    assert s._inner.embed is embed
    # 안 넘기면 None
    assert get_searcher("t", FakeRepo(), {"index_version": IV})._inner.embed is None


@pytest.mark.parametrize(
    "override",
    [{"corpus": "law"}, {"mode": "vector"}, {"k": 3}],
    ids=["corpus", "mode", "k"],
)
def test_결과_머리가_요청과_다르면_오류(override):
    _register("t", lambda: [_hit("a", 1.0, 1)], override=override)
    s = get_searcher("t", FakeRepoBoth(), {"index_version": IV})
    with pytest.raises(SearchContractViolationError, match="요청과 다르다"):
        _search(s)


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


def test_result의_index_version만_다르면_오류():
    # 조각은 설정 판과 같지만 결과 머리의 판이 다른 경우
    _register("t", lambda: [_hit("a", 1.0, 1)], result_index_version="cite-idx-v2")
    with pytest.raises(IndexVersionMismatchError, match="cite-idx-v1"):
        _search(_get())


def test_같은_이름에_다른_클래스를_또_등록하면_오류():
    _register("t", lambda: [])
    with pytest.raises(ValueError, match="이미 등록"):
        _register("t", lambda: [])


def test_impl_이름으로_구현_모듈을_그때_import한다(monkeypatch):
    # design 7-1: impl: fake → patent_ai.retrieval.fake를 import하고, 그 모듈이 자기를 등록한다
    import sys

    monkeypatch.delitem(sys.modules, "patent_ai.retrieval.fake", raising=False)
    assert "fake" not in contract._REGISTRY
    s = get_searcher("fake", FakeRepo(), {"index_version": IV})
    assert isinstance(s, contract.CheckedSearcher)
    assert "fake" in contract._REGISTRY


def test_모듈이_없는_impl은_UnknownImplError():
    with pytest.raises(UnknownImplError, match="nothere"):
        get_searcher("nothere", FakeRepo(), {"index_version": IV})


def test_점이나_슬래시가_든_impl은_import하지_않는다():
    with pytest.raises(UnknownImplError):
        get_searcher("os.path", FakeRepo(), {"index_version": IV})
