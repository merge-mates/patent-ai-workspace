"""BM25 구현 시험 (requirements 5·7). 지어낸 조각·메모리 저장소만 쓰고 네트워크·DB·PDF는 안 쓴다."""

import math
from datetime import date

import pytest

from patent_ai.retrieval.contract import get_searcher
from patent_ai.retrieval.errors import ModeNotSupportedError
from patent_ai.retrieval.repository import InMemoryChunkRepository
from patent_ai.retrieval.schemas import Chunk, Edition, Location
from patent_ai.retrieval.tokenizer import KiwiTokenizer, make_tokenizer

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


# --- 낱말 자르기 고르기 (#66 law_bm25를 합침) ---


def test_두_글자씩_겹쳐_자른다():
    assert make_tokenizer("char_bigram").tokenize("발명은 쉽게") == ["발명", "명은", "쉽게"]
    assert make_tokenizer("char_bigram").tokenize("및 제1항") == ["및", "제1", "1항"]
    assert make_tokenizer("whitespace").tokenize("발명은  쉽게\n발명") == ["발명은", "쉽게", "발명"]


def test_모르는_tokenizer는_막는다(repo):
    with pytest.raises(ValueError, match="char_bigram"):
        get_searcher("bm25", repo, {**SETTINGS, "tokenizer": "morpheme"})


def test_pos_tags는_kiwi가_아니면_막는다(repo):
    # 설정에 적힌 품사가 점수에 안 쓰이는데 조용히 넘어가지 않게
    with pytest.raises(ValueError, match="pos_tags"):
        get_searcher("bm25", repo, {**SETTINGS, "tokenizer": "char_bigram", "pos_tags": ["NNG"]})


# --- 법령 (두 글자 낱말, 기준일 판) ---

LV = "law-idx-v1"
OLD = Edition(status="confirmed", effective_from=date(2020, 3, 11), effective_to=date(2020, 10, 19))
NEW = Edition(status="confirmed", effective_from=date(2020, 10, 20))


def _law(doc_id: str, loc: int, text: str, edition: Edition = NEW) -> Chunk:
    return Chunk(
        chunk_id=f"{LV}:{doc_id}:{loc}",
        index_version=LV,
        doc_id=doc_id,
        chunk_kind="article",
        location=Location(kind="article", start=loc, end=loc, label=str(loc)),
        edition=edition,
        text=text,
    )


def _law_searcher(chunks):
    repo = InMemoryChunkRepository({"law": chunks})
    return get_searcher("bm25", repo, {"index_version": LV, "tokenizer": "char_bigram"})


def test_점수는_lucene_BM25_공식과_같다():
    # 문서 2개, 질의 낱말이 한 문서에만 한 번: idf = ln((2-1+0.5)/(1+0.5) + 1) = ln 2
    # 길이가 평균과 같으면 tf 항 = 1 / (1 + k1) (lucene은 Okapi의 (k1+1)을 곱하지 않음. 순위는 같음)
    res = _law_searcher([_law("d", 1, "가나"), _law("d", 2, "다라")]).search(
        "가나", "law", "bm25", k=5
    )
    assert [h.location.start for h in res.hits] == [1]
    assert res.hits[0].score == pytest.approx(math.log(2) / 2.5)


def test_법령_드문_낱말이_겹치는_조각이_위로():
    chunks = [
        _law("d", 290002, "제29조(특허요건) ② 통상의 지식을 가진 사람이 쉽게 발명할 수 있으면"),
        _law("d", 420004, "제42조(특허출원) ④ 청구항은 발명이 명확하고 간결하게 적혀 있을 것"),
        _law("d", 10000, "제1조(목적) 이 법은 발명을 보호하고 장려한다"),
    ]
    q = "청구항의 기재가 불비하여 발명이 명확하고 간결하게 적혀 있지 않습니다"
    res = _law_searcher(chunks).search(q, "law", "bm25", k=3)
    assert res.hits[0].location.start == 420004


def test_기준일에_효력_있는_판만_나온다():
    chunks = [
        _law("특허법_old", 290002, "쉽게 발명할 수 있으면", OLD),
        _law("특허법_new", 290002, "쉽게 발명할 수 있으면", NEW),
    ]
    s = _law_searcher(chunks)
    old = s.search("쉽게 발명", "law", "bm25", 5, as_of=date(2020, 8, 1))
    new = s.search("쉽게 발명", "law", "bm25", 5, as_of=date(2021, 1, 1))
    assert [h.doc_id for h in old.hits] == ["특허법_old"]
    assert [h.doc_id for h in new.hits] == ["특허법_new"]


def test_통계는_기준일_범위_안_조각으로만_센다():
    # 옛 판에만 '가나'가 흔하다. 기준일 검색 점수는 옛 판을 아예 뺀 저장소 점수와 같아야 한다
    new = [_law("n", 1, "가나 다라"), _law("n", 2, "마바 사아")]
    old = [_law("o", i, "가나 가나 가나", OLD) for i in range(1, 6)]
    day = date(2021, 1, 1)
    with_old = _law_searcher(new + old).search("가나", "law", "bm25", 5, as_of=day)
    only_new = _law_searcher(new).search("가나", "law", "bm25", 5, as_of=day)
    assert [h.chunk_id for h in with_old.hits] == [h.chunk_id for h in only_new.hits]
    assert with_old.hits[0].score == pytest.approx(only_new.hits[0].score)


def test_판본_모르는_조각은_빠지고_센다():
    unknown = Edition(status="unverified")
    chunks = [_law("a", 1, "가나"), _law("b", 1, "가나", unknown)]
    res = _law_searcher(chunks).search("가나", "law", "bm25", 5, as_of=date(2021, 1, 1))
    assert [h.doc_id for h in res.hits] == ["a"]
    assert res.skipped_unverified_edition == 1
