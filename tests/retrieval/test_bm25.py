"""BM25 구현 시험 (requirements 5·7). 지어낸 조각·메모리 저장소만 쓰고 네트워크·DB·PDF는 안 쓴다."""

import pytest

from patent_ai.retrieval.contract import get_searcher
from patent_ai.retrieval.errors import ModeNotSupportedError
from patent_ai.retrieval.repository import InMemoryChunkRepository
from patent_ai.retrieval.schemas import Chunk, Edition, Location
from patent_ai.retrieval.tokenizer import KiwiTokenizer

IV = "cite-idx-v1"
SETTINGS = {"index_version": IV}


def _chunk(doc: str, no: int, text: str) -> Chunk:
    return Chunk(
        chunk_id=f"{IV}:{doc}:[{no:04d}]",
        index_version=IV,
        doc_id=doc,
        chunk_kind="body",
        location=Location(kind="paragraph", start=no, end=no, label=f"[{no:04d}]"),
        edition=Edition(status="not_applicable"),
        text=text,
    )


@pytest.fixture(scope="module")
def repo() -> InMemoryChunkRepository:
    rows = [
        _chunk("DOC-A", 1, "열전도성 필러를 포함하는 방열 시트"),
        _chunk("DOC-A", 2, "방열 시트의 두께와 접착층 구조"),
        _chunk("DOC-A", 3, "배터리 셀 냉각 장치"),
        _chunk("DOC-B", 1, "silicon nitride 입자를 포함하는 조성물"),
        _chunk("DOC-C", 1, "동일 문장 동일 문장"),
        _chunk("DOC-C", 2, "동일 문장 동일 문장"),
    ]
    return InMemoryChunkRepository({"cite": rows})


@pytest.fixture(scope="module")
def searcher(repo):
    # Kiwi 생성이 느려 모듈에서 한 번만 만든다 (계약 래퍼 통과)
    return get_searcher("bm25", repo, SETTINGS)


def test_토큰에_조사와_어미가_없다():
    toks = KiwiTokenizer().tokenize("열전도성 필러를 포함하는 방열 시트")
    assert "필러" in toks and "시트" in toks and "방열" in toks
    assert "를" not in toks and "는" not in toks and "성" not in toks


def test_영어는_소문자로_합친다():
    assert "silicon" in KiwiTokenizer().tokenize("Silicon Nitride")


def test_품사_목록을_바꾸면_토큰이_달라진다():
    only_nnp = KiwiTokenizer(["NNP"]).tokenize("열전도성 필러를 포함하는 방열 시트")
    assert "시트" not in only_nnp and "필러" in only_nnp


def test_겹치는_낱말이_많은_조각이_1위(searcher):
    res = searcher.search("방열 시트 필러", "cite", "bm25", 3, doc_ids=["DOC-A"])
    assert res.status is None
    assert res.hits[0].chunk_id == f"{IV}:DOC-A:[0001]"
    assert [h.rank for h in res.hits] == list(range(1, len(res.hits) + 1))
    # 겹치는 낱말이 없는 조각(배터리)은 0점이라 hit에 없다
    assert f"{IV}:DOC-A:[0003]" not in [h.chunk_id for h in res.hits]


def test_검색_범위_밖_문헌은_안_나온다(searcher):
    res = searcher.search("silicon 방열", "cite", "bm25", 10, doc_ids=["DOC-A"])
    assert {h.doc_id for h in res.hits} == {"DOC-A"}


def test_k가_조각_수보다_커도_오류_없이_있는_만큼(searcher):
    res = searcher.search("방열 시트", "cite", "bm25", 10, doc_ids=["DOC-A"])
    assert 1 <= len(res.hits) <= 3


def test_k가_작으면_k개만(searcher):
    res = searcher.search("방열 시트", "cite", "bm25", 1, doc_ids=["DOC-A"])
    assert len(res.hits) == 1


def test_같은_점수는_chunk_id_순(searcher):
    res = searcher.search("동일 문장", "cite", "bm25", 5, doc_ids=["DOC-C"])
    assert [h.chunk_id for h in res.hits] == [f"{IV}:DOC-C:[0001]", f"{IV}:DOC-C:[0002]"]
    assert res.hits[0].score == res.hits[1].score


def test_겹치는_낱말이_없으면_조회_범위_내_없음(searcher):
    res = searcher.search("양자 컴퓨터", "cite", "bm25", 5, doc_ids=["DOC-A"])
    assert res.hits == []
    assert res.status == "not_found_in_scope"


def test_한국어_질의로_영어_조각은_점수가_없다(searcher):
    res = searcher.search("질화 규소 분말", "cite", "bm25", 5, doc_ids=["DOC-B"])
    assert res.status == "not_found_in_scope"


def test_질의가_비어도_조회_범위_내_없음(searcher):
    res = searcher.search("를 은 는", "cite", "bm25", 5, doc_ids=["DOC-A"])
    assert res.status == "not_found_in_scope"


def test_문헌_조각이_없으면_본문_없음(searcher):
    res = searcher.search("방열", "cite", "bm25", 5, doc_ids=["DOC-NONE"])
    assert res.status == "unverified"
    assert res.status_reason == "body_missing"


def test_vector_방식은_막는다(repo):
    # 래퍼는 vector를 통과시키므로 구현이 직접 막는다
    inner = get_searcher("bm25", repo, SETTINGS)._inner
    with pytest.raises(ModeNotSupportedError):
        inner.search("방열", "cite", "vector", 3, doc_ids=["DOC-A"])


def test_같은_질의를_두_번_해도_같은_결과(searcher):
    a = searcher.search("방열 시트", "cite", "bm25", 3, doc_ids=["DOC-A"])
    b = searcher.search("방열 시트", "cite", "bm25", 3, doc_ids=["DOC-A"])
    assert a == b


def test_k1과_b_설정이_점수에_반영된다(repo):
    base = get_searcher("bm25", repo, SETTINGS)
    tuned = get_searcher("bm25", repo, {**SETTINGS, "bm25": {"k1": 3.0, "b": 0.1}})
    q = ("방열 시트", "cite", "bm25", 3)
    s0 = base.search(*q, doc_ids=["DOC-A"]).hits[0].score
    s1 = tuned.search(*q, doc_ids=["DOC-A"]).hits[0].score
    assert s0 != s1
