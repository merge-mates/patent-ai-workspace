"""weighted_sum(점수 min-max 정규화 후 가중합) 검색기 테스트. 네트워크 없음."""

import pytest

from patent_ai.retrieval.contract import CheckedSearcher, get_searcher
from patent_ai.retrieval.errors import ModeNotSupportedError
from patent_ai.retrieval.repository import InMemoryChunkRepository
from patent_ai.retrieval.schemas import Chunk, Edition, Location

IV = "cite-idx-v2"
W = {"weights": {"bm25": 0.5, "vector": 0.5}}


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


# 질의 "방열 시트" 벡터 [1, 0]. 벡터 점수(코사인): 1번 0.0, 2번 1.0, 3번 0.6
# BM25: 1번 > 2번 (3번은 낱말이 없어 0점이라 안 돌려준다)
CHUNKS = [
    _chunk("D", 1, "방열 시트 방열 시트", [0.0, 1.0]),
    _chunk("D", 2, "방열 시트 필러 접착층", [1.0, 0.0]),
    _chunk("D", 3, "배터리 냉각 장치", [0.6, 0.8]),
]


def _searcher(chunks=CHUNKS, embed=lambda q: [1.0, 0.0], **over):
    repo = InMemoryChunkRepository({"cite": chunks})
    settings = {"index_version": IV, "weighted_sum": W, **over}
    return get_searcher("weighted_sum", repo, settings, embed)


def _search(s, k=3, query="방열 시트", **kw):
    return s.search(query, "cite", "hybrid", k, **kw)


def _raw(chunks, query="방열 시트", embed=lambda q: [1.0, 0.0]):
    """안쪽 두 검색기의 원점수를 받아 둔다 (기대값 계산 입력)."""
    repo = InMemoryChunkRepository({"cite": chunks})
    s = {"index_version": IV}
    b = get_searcher("bm25", repo, s).search(query, "cite", "bm25", 3)
    v = get_searcher("vector", repo, s, embed).search(query, "cite", "vector", 3)
    return {h.location.start: h.score for h in b.hits}, {h.location.start: h.score for h in v.hits}


def test_정규화_계산을_손으로_맞춘_값과_비교():
    b, v = _raw(CHUNKS)
    # 전제: BM25는 1번 > 2번, 3번 없음 / 벡터는 2번 1.0 > 3번 0.6 > 1번 0.0
    assert set(b) == {1, 2} and b[1] > b[2]
    assert v[2] == pytest.approx(1.0) and v[3] == pytest.approx(0.6) and v[1] == pytest.approx(0.0)
    # 스펙: min-max로 [0, 1]. BM25는 1번 1.0, 2번 0.0. 벡터는 2번 1.0, 3번 0.6, 1번 0.0
    # 가중합 0.5/0.5 -> 1번 0.5, 2번 0.5, 3번 0.3 (3번은 BM25 안 돌려줌 -> 0)
    res = _search(_searcher())
    got = {h.location.start: h.score for h in res.hits}
    assert got[1] == pytest.approx(0.5)
    assert got[2] == pytest.approx(0.5)
    assert got[3] == pytest.approx(0.3)
    # 1번과 2번은 점수가 같아 chunk_id 순, 그 뒤 3번
    assert [h.location.start for h in res.hits] == [1, 2, 3]
    assert [h.rank for h in res.hits] == [1, 2, 3]
    assert res.mode == "hybrid"


def test_한쪽_점수가_모두_같으면_그쪽은_전부_1점():
    # BM25가 돌려준 조각이 한 개뿐 (max == min) -> 그 조각 BM25 정규화 값 1.0
    chunks = [
        _chunk("D", 1, "방열 시트", [0.0, 1.0]),
        _chunk("D", 2, "냉각 장치", [1.0, 0.0]),
    ]
    res = _search(_searcher(chunks))
    got = {h.location.start: h.score for h in res.hits}
    # 1번: BM25 1.0, 벡터 0.0(최소) -> 0.5 / 2번: BM25 0, 벡터 1.0 -> 0.5
    assert got == {1: pytest.approx(0.5), 2: pytest.approx(0.5)}


def test_가중치_1대0은_BM25_순서와_같다():
    s = _searcher(weighted_sum={"weights": {"bm25": 1.0, "vector": 0.0}})
    res = _search(s)
    assert [h.location.start for h in res.hits][:2] == [1, 2]
    assert res.hits[0].score == pytest.approx(1.0)


def test_가중치_0대1은_벡터_순서와_같다():
    s = _searcher(weighted_sum={"weights": {"bm25": 0.0, "vector": 1.0}})
    res = _search(s)
    assert [h.location.start for h in res.hits] == [2, 3, 1]


def test_같은_점수는_chunk_id_순():
    chunks = [_chunk("B", 1, "동일 문장", [1.0, 0.0]), _chunk("A", 1, "동일 문장", [1.0, 0.0])]
    res = _search(_searcher(chunks), query="동일 문장")
    assert [h.doc_id for h in res.hits] == ["A", "B"]


def test_바깥_k만큼만_돌려준다():
    res = _search(_searcher(), k=1)
    assert len(res.hits) == 1 and res.scope.k == 1


def test_계약_래퍼를_거친다():
    assert isinstance(_searcher(), CheckedSearcher)


def test_BM25가_비어도_벡터_점수로_hit():
    res = _search(_searcher(), query="전혀 다른 질의 xyz")
    assert res.status is None
    assert [h.location.start for h in res.hits] == [2, 3, 1]


def test_문헌_조각이_없으면_본문_없음():
    res = _search(_searcher(), doc_ids=["없는문헌"])
    assert res.status == "unverified" and res.status_reason == "body_missing"


def test_조각에_벡터가_없으면_조용히_BM25만으로_섞지_않는다():
    chunks = [_chunk("D", 1, "방열 시트", [1.0, 0.0]), _chunk("D", 2, "방열 시트 구조", None)]
    with pytest.raises(ValueError, match="embedding"):
        _search(_searcher(chunks))


def test_weighted_sum_칸이_없으면_멈춘다():
    repo = InMemoryChunkRepository({"cite": CHUNKS})
    with pytest.raises(ValueError, match="weighted_sum"):
        get_searcher("weighted_sum", repo, {"index_version": IV}, lambda q: [1.0, 0.0])


@pytest.mark.parametrize(
    "bad",
    [
        {"weights": {"bm25": 1.0}},
        {"weights": {"bm25": 1.0, "vector": 1.0, "x": 1.0}},
        {"weights": {"bm25": -0.1, "vector": 1.0}},
        {"weights": {"bm25": 0.0, "vector": 0.0}},
        {"weights": {"bm25": float("nan"), "vector": 1.0}},
        {"weights": {"bm25": float("inf"), "vector": 1.0}},
        {"weights": {"bm25": True, "vector": 1.0}},
        {},
    ],
)
def test_잘못된_가중치는_멈춘다(bad):
    with pytest.raises(ValueError):
        _searcher(weighted_sum=bad)


def test_다른_mode로_부르면_거절():
    with pytest.raises(ModeNotSupportedError):
        _searcher().search("방열 시트", "cite", "bm25", 3)


# ---- 자료 유형·선고일 미리 거르기 (#24 24a) ----
def _law_repo():
    def law(cid, kind, source_kind, decided_on=None):
        return Chunk(
            chunk_id=f"law-idx-v3:{cid}",
            index_version="law-idx-v3",
            doc_id=cid,
            chunk_kind=kind,
            location=Location(kind="article", label=cid),
            edition=Edition(status="not_applicable")
            if kind == "judgment"
            else Edition(status="confirmed", effective_from="2020-01-01"),
            text="방열 시트",
            embedding=[1.0, 0.0],
            source_kind=source_kind,
            decided_on=decided_on,
            speaker="court" if decided_on else None,
        )

    return InMemoryChunkRepository(
        {
            "law": [
                law("art", "article", "statute"),
                law("gl", "guideline", "guideline"),
                law("p-early", "judgment", "precedent", "2020-05-01"),
                law("p-late", "judgment", "precedent", "2022-05-01"),
                law("p-null", "judgment", "precedent", None),
            ]
        }
    )


def _law_searcher(impl, settings):
    return get_searcher(
        impl,
        _law_repo(),
        {"index_version": "law-idx-v3", "tokenizer": "whitespace", **settings},
        lambda q: [1.0, 0.0],
    )


def test_chunk_kinds로_거르면_조문은_안_나온다_weighted_sum():
    res = _law_searcher(
        "weighted_sum", {"weighted_sum": {"weights": {"bm25": 0.5, "vector": 0.5}}}
    ).search("방열 시트", "law", "hybrid", 10, chunk_kinds=["guideline"])
    assert [h.chunk_id for h in res.hits] == ["law-idx-v3:gl"]
    assert res.scope.chunk_kinds == ["guideline"]


def test_유형_조각이_0개면_body_missing_weighted_sum():
    repo = InMemoryChunkRepository(
        {"law": [c for c in _law_repo()._tables["law"] if c.doc_id == "art"]}
    )
    s = get_searcher(
        "weighted_sum",
        repo,
        {
            "index_version": "law-idx-v3",
            "tokenizer": "whitespace",
            **{"weighted_sum": {"weights": {"bm25": 0.5, "vector": 0.5}}},
        },
        lambda q: [1.0, 0.0],
    )
    res = s.search("방열 시트", "law", "hybrid", 10, chunk_kinds=["guideline"])
    assert (res.status, res.status_reason) == ("unverified", "body_missing")


def test_선고일_거르기와_날짜_모름_셈_weighted_sum():
    from datetime import date

    res = _law_searcher(
        "weighted_sum", {"weighted_sum": {"weights": {"bm25": 0.5, "vector": 0.5}}}
    ).search(
        "방열 시트",
        "law",
        "hybrid",
        10,
        source_kinds=["precedent"],
        decided_on_or_before=date(2021, 1, 1),
    )
    assert [h.chunk_id for h in res.hits] == ["law-idx-v3:p-early"]
    assert res.skipped_unknown_date == 1
