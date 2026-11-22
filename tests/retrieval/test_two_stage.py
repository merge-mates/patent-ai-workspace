"""two_stage(BM25 후보 -> 벡터 재순위) 검색기 테스트. 메모리 저장소 + 지어낸 벡터, 네트워크 없음."""

import pytest

from patent_ai.retrieval.contract import CheckedSearcher, get_searcher
from patent_ai.retrieval.errors import ModeNotSupportedError
from patent_ai.retrieval.repository import InMemoryChunkRepository
from patent_ai.retrieval.schemas import Chunk, Edition, Location

IV = "cite-idx-v2"


def _chunk(doc, no, text, emb):
    return Chunk(
        chunk_id=f"{IV}:{doc}:[{no:04d}]",
        index_version=IV,
        doc_id=doc,
        chunk_kind="body",
        location=Location(kind="paragraph", start=no, end=no, label=f"[{no:04d}]"),
        edition=Edition(status="not_applicable"),
        text=text,
        embedding=emb,
    )


# 질의 "방열 시트"의 벡터는 [1, 0]. BM25는 낱말이 겹치는 1~3번만 돌려준다 (4번은 0점)
# 벡터 점수는 4번(1.0) > 2번(0.8) > 3번(0.6) > 1번(0.0)
CHUNKS = [
    _chunk("D", 1, "방열 시트 구조 방열 시트", [0.0, 1.0]),  # BM25 1~2위, 벡터 꼴찌
    _chunk("D", 2, "방열 시트 필러 접착층", [0.8, 0.6]),
    _chunk("D", 3, "방열 시트", [0.6, 0.8]),
    _chunk("D", 4, "배터리 냉각 장치", [1.0, 0.0]),  # BM25엔 없고 벡터 1위
]


def _searcher(chunks=CHUNKS, n=3, embed=lambda q: [1.0, 0.0], **over):
    repo = InMemoryChunkRepository({"cite": chunks})
    settings = {"index_version": IV, "two_stage": {"candidates": n}, **over}
    return get_searcher("two_stage", repo, settings, embed)


def _search(s, k=10, query="방열 시트", **kw):
    return s.search(query, "cite", "hybrid", k, **kw)


def test_후보_밖_조각은_벡터가_높아도_나오지_않는다():
    res = _search(_searcher(n=3))
    assert 4 not in [h.location.start for h in res.hits]


def test_후보_안에서는_벡터_순서로_다시_줄세운다():
    res = _search(_searcher(n=3))
    assert [h.location.start for h in res.hits] == [2, 3, 1]
    assert [h.rank for h in res.hits] == [1, 2, 3]
    assert res.hits[0].score == pytest.approx(0.8)  # 점수 = 벡터 점수
    keys = [(-h.score, h.chunk_id) for h in res.hits]
    assert keys == sorted(keys)


def test_후보_수가_작으면_결과가_그만큼만():
    # BM25 상위 2개(1번, 3번)만 후보. 벡터가 더 높은 2번은 후보 밖이라 빠지고, 벡터 순서 [3, 1]
    res = _search(_searcher(n=2))
    assert [h.location.start for h in res.hits] == [3, 1]


def test_바깥_k가_후보_수보다_작으면_위_k개만():
    s = _searcher(n=3)
    res = _search(s, k=1)
    assert [h.location.start for h in res.hits] == [2]
    assert res.scope.k == 1


def test_결과_머리는_요청과_같다():
    res = _search(_searcher(), k=2, doc_ids=["D"])
    assert res.mode == "hybrid" and res.corpus == "cite"
    assert res.index_version == IV
    assert res.scope.doc_ids == ["D"]


def test_계약_래퍼를_거친다():
    assert isinstance(_searcher(), CheckedSearcher)


def test_BM25_후보가_없으면_범위_안_없음():
    # 벡터만으로 되돌아가지 않는다 (2단계의 후보는 BM25가 정한다)
    res = _search(_searcher(), query="전혀 다른 질의 xyz")
    assert res.status == "not_found_in_scope"
    assert res.hits == []


def test_문헌_조각이_없으면_본문_없음():
    res = _search(_searcher(), doc_ids=["없는문헌"])
    assert res.status == "unverified" and res.status_reason == "body_missing"
    assert res.hits == []


def test_후보_조각에_벡터가_없으면_조용히_넘어가지_않는다():
    chunks = [_chunk("D", 1, "방열 시트", [1.0, 0.0]), _chunk("D", 2, "방열 시트 구조", None)]
    with pytest.raises(ValueError, match="embedding"):
        _search(_searcher(chunks))


def test_two_stage_칸이_없으면_멈춘다():
    repo = InMemoryChunkRepository({"cite": CHUNKS})
    with pytest.raises(ValueError, match="two_stage"):
        get_searcher("two_stage", repo, {"index_version": IV}, lambda q: [1.0, 0.0])


@pytest.mark.parametrize(
    "bad",
    [{}, {"candidates": 0}, {"candidates": -1}, {"candidates": 2.5}, {"candidates": "3"},
     {"candidates": True}, {"candidates": None}],
)  # fmt: skip
def test_잘못된_후보_수는_멈춘다(bad):
    with pytest.raises(ValueError):
        _searcher(two_stage=bad)


def test_다른_mode로_부르면_거절():
    with pytest.raises(ModeNotSupportedError):
        _searcher().search("방열 시트", "cite", "bm25", 3)
