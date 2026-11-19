"""law_bm25 검색기 테스트 (#66 task 3). DB·네트워크 없이 메모리 저장소로."""

import math
from datetime import date

import pytest

from patent_ai.retrieval.contract import get_searcher
from patent_ai.retrieval.errors import ModeNotSupportedError
from patent_ai.retrieval.law_bm25 import tokenize
from patent_ai.retrieval.repository import InMemoryChunkRepository
from patent_ai.retrieval.schemas import Chunk, Edition, Location

V = "law-idx-v1"
OLD = Edition(status="confirmed", effective_from=date(2020, 3, 11), effective_to=date(2020, 10, 19))
NEW = Edition(status="confirmed", effective_from=date(2020, 10, 20))


def _chunk(doc_id: str, loc: int, text: str, edition: Edition = NEW) -> Chunk:
    return Chunk(
        chunk_id=f"{V}:{doc_id}:{loc}",
        index_version=V,
        doc_id=doc_id,
        chunk_kind="article",
        location=Location(kind="article", start=loc, end=loc, label=str(loc)),
        edition=edition,
        text=text,
    )


def _searcher(chunks, **settings):
    repo = InMemoryChunkRepository({"law": chunks})
    return get_searcher("law_bm25", repo, {"index_version": V, **settings})


# --- 낱말 자르기 ---


def test_두_글자씩_겹쳐_자른다():
    assert tokenize("발명은 쉽게", "char_bigram") == ["발명", "명은", "쉽게"]
    assert tokenize("및 제1항", "char_bigram") == ["및", "제1", "1항"]
    assert tokenize("발명은  쉽게\n발명", "whitespace") == ["발명은", "쉽게", "발명"]


def test_모르는_자르기_방식은_막는다():
    with pytest.raises(ValueError):
        _searcher([_chunk("d", 1, "가나")], tokenizer="morpheme")


# --- 점수와 순위 ---


def test_점수는_Okapi_BM25_공식과_같다():
    # 문서 2개, 질의 낱말이 한 문서에만 한 번: idf = ln((2-1+0.5)/(1+0.5) + 1) = ln 2
    # 길이가 평균과 같으면 tf 항 = 1*(k1+1)/(1+k1) = 1
    res = _searcher([_chunk("d", 1, "가나"), _chunk("d", 2, "다라")]).search(
        "가나", "law", "bm25", k=5
    )
    assert [h.location.start for h in res.hits] == [1]
    assert res.hits[0].score == pytest.approx(math.log(2))
    assert res.hits[0].rank == 1


def test_드문_낱말이_겹치는_조각이_위로():
    chunks = [
        _chunk("d", 290002, "제29조(특허요건) ② 통상의 지식을 가진 사람이 쉽게 발명할 수 있으면"),
        _chunk("d", 420004, "제42조(특허출원) ④ 청구항은 발명이 명확하고 간결하게 적혀 있을 것"),
        _chunk("d", 10000, "제1조(목적) 이 법은 발명을 보호하고 장려한다"),
    ]
    q = "청구항의 기재가 불비하여 발명이 명확하고 간결하게 적혀 있지 않습니다"
    res = _searcher(chunks).search(q, "law", "bm25", k=3)
    assert res.hits[0].location.start == 420004


def test_점수_0은_빼고_하나도_없으면_범위_내_없음():
    res = _searcher([_chunk("d", 1, "가나다")]).search("마바사", "law", "bm25", k=5)
    assert res.hits == []
    assert res.status == "not_found_in_scope"


def test_같은_점수면_chunk_id_순서():
    chunks = [_chunk("b", 1, "가나"), _chunk("a", 1, "가나"), _chunk("c", 1, "다라")]
    res = _searcher(chunks).search("가나", "law", "bm25", k=5)
    assert [h.doc_id for h in res.hits] == ["a", "b"]


def test_k개까지만():
    chunks = [_chunk("d", i, "가나 다라") for i in range(1, 6)]
    assert len(_searcher(chunks).search("가나", "law", "bm25", k=2).hits) == 2


# --- 판본 기준일 ---


def test_기준일에_효력_있는_판만_나온다():
    chunks = [
        _chunk("특허법_old", 290002, "쉽게 발명할 수 있으면", OLD),
        _chunk("특허법_new", 290002, "쉽게 발명할 수 있으면", NEW),
    ]
    s = _searcher(chunks)
    assert [
        h.doc_id for h in s.search("쉽게 발명", "law", "bm25", 5, as_of=date(2020, 8, 1)).hits
    ] == ["특허법_old"]
    assert [
        h.doc_id for h in s.search("쉽게 발명", "law", "bm25", 5, as_of=date(2021, 1, 1)).hits
    ] == ["특허법_new"]


def test_판본_모르는_조각은_빠지고_센다():
    unknown = Edition(status="unverified")
    chunks = [_chunk("a", 1, "가나"), _chunk("b", 1, "가나", unknown)]
    res = _searcher(chunks).search("가나", "law", "bm25", 5, as_of=date(2021, 1, 1))
    assert [h.doc_id for h in res.hits] == ["a"]
    assert res.skipped_unverified_edition == 1


def test_고른_문서에_조각이_없으면_본문_없음():
    res = _searcher([_chunk("a", 1, "가나")]).search("가나", "law", "bm25", 5, doc_ids=["zz"])
    assert res.status == "unverified" and res.status_reason == "body_missing"


def test_벡터_방식은_이_구현이_안_한다():
    with pytest.raises(ModeNotSupportedError):
        _searcher([_chunk("a", 1, "가나")]).search("가나", "law", "vector", 5)
