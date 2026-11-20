"""hybrid(RRF) 검색기 테스트. 메모리 저장소 + 지어낸 벡터 + 녹화 질의 벡터, 네트워크 없음."""

import json

import pytest

from patent_ai.retrieval.contract import get_searcher
from patent_ai.retrieval.errors import ModeNotSupportedError, RecordedEmbeddingMissing
from patent_ai.retrieval.hybrid import rrf
from patent_ai.retrieval.repository import InMemoryChunkRepository
from patent_ai.retrieval.schemas import Chunk, Edition, Location

IV = "cite-idx-v2"
HYBRID = {"rrf_k": 60, "weights": {"bm25": 0.5, "vector": 0.5}}


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


# 질의 "방열 시트"의 벡터는 [1, 0]
CHUNKS = [
    _chunk("D", 1, "방열 시트 구조", [0.0, 1.0]),  # BM25 상위, 벡터 꼴찌
    _chunk("D", 2, "방열 시트 필러 접착층", [1.0, 0.0]),  # BM25에도 있고 벡터 1위
    _chunk("D", 3, "배터리 냉각 장치", [0.8, 0.6]),  # BM25엔 없고 벡터 2위
]


def _searcher(chunks=CHUNKS, embed=lambda q: [1.0, 0.0], **over):
    repo = InMemoryChunkRepository({"cite": chunks})
    settings = {"index_version": IV, "hybrid": HYBRID, **over}
    return get_searcher("hybrid", repo, settings, embed)


def _search(s, k=3, query="방열 시트", **kw):
    return s.search(query, "cite", "hybrid", k, **kw)


# --- rrf 순수 함수 ---
def test_rrf_두_목록에_다_있는_조각이_1위():
    w = {"bm25": 0.5, "vector": 0.5}
    scores = rrf({"bm25": ["a", "b"], "vector": ["b", "c"]}, w, 60)
    order = sorted(scores, key=lambda c: (-scores[c], c))
    assert order == ["b", "a", "c"]
    assert scores["b"] == pytest.approx(0.5 / 62 + 0.5 / 61)
    assert scores["a"] == pytest.approx(0.5 / 61)  # 한쪽에만 있으면 그쪽 항만


def test_rrf_가중치가_점수에_곱해진다():
    scores = rrf({"bm25": ["a"], "vector": ["b"]}, {"bm25": 1.0, "vector": 0.0}, 60)
    assert scores == {"a": pytest.approx(1 / 61), "b": pytest.approx(0.0)}


# --- 검색기 ---
def test_두_쪽에_다_걸린_조각이_위():
    res = _search(_searcher())
    assert res.mode == "hybrid"
    assert res.scope.k == 3
    assert res.hits[0].location.start == 2
    assert [h.rank for h in res.hits] == [1, 2, 3]
    keys = [(-h.score, h.chunk_id) for h in res.hits]
    assert keys == sorted(keys)


def test_바깥_k가_달라도_1위는_같다():
    s = _searcher()
    assert _search(s, k=1).hits[0].chunk_id == _search(s, k=3).hits[0].chunk_id
    assert len(_search(s, k=1).hits) == 1


def test_같은_점수는_chunk_id_순():
    chunks = [_chunk("B", 1, "동일 문장", [1.0, 0.0]), _chunk("A", 1, "동일 문장", [1.0, 0.0])]
    res = _search(_searcher(chunks), query="동일 문장")
    assert [h.doc_id for h in res.hits] == ["A", "B"]


def test_BM25쪽이_비어도_벡터_순위로_hit():
    # 질의 낱말이 어느 조각에도 없으면 BM25는 not_found_in_scope. 벡터만으로 섞인다
    res = _search(_searcher(), query="전혀 다른 질의 xyz")
    assert res.status is None
    assert [h.location.start for h in res.hits] == [2, 3, 1]


def test_문헌_조각이_없으면_본문_없음():
    res = _search(_searcher(), doc_ids=["없는문헌"])
    assert res.status == "unverified" and res.status_reason == "body_missing"
    assert res.hits == []


def test_녹화_질의_벡터를_쓴다(tmp_path):
    path = tmp_path / "qv.json"
    path.write_text(json.dumps({"방열 시트": [1.0, 0.0]}), encoding="utf-8")
    s = _searcher(embed=None, query_vectors=str(path))
    assert _search(s).hits[0].location.start == 2
    with pytest.raises(RecordedEmbeddingMissing):
        _search(s, query="녹화에 없는 질의")


# --- 실패 ---
def test_hybrid_칸이_없으면_멈춘다():
    repo = InMemoryChunkRepository({"cite": CHUNKS})
    with pytest.raises(ValueError, match="hybrid"):
        get_searcher("hybrid", repo, {"index_version": IV}, lambda q: [1.0, 0.0])


@pytest.mark.parametrize(
    "bad",
    [
        {"rrf_k": 60, "weights": {"bm25": 1.0}},  # 키가 모자람
        {"rrf_k": 60, "weights": {"bm25": 1.0, "vector": 1.0, "x": 1.0}},  # 키가 다름
        {"rrf_k": 60, "weights": {"bm25": -0.1, "vector": 1.0}},  # 음수
        {"rrf_k": 60, "weights": {"bm25": 0.0, "vector": 0.0}},  # 둘 다 0
        {"rrf_k": 0, "weights": {"bm25": 0.5, "vector": 0.5}},
        {"rrf_k": -5, "weights": {"bm25": 0.5, "vector": 0.5}},
        {"weights": {"bm25": 0.5, "vector": 0.5}},  # rrf_k 없음
        {"rrf_k": 60},  # weights 없음
    ],
)
def test_잘못된_hybrid_설정은_멈춘다(bad):
    with pytest.raises(ValueError):
        _searcher(hybrid=bad)


def test_다른_mode로_부르면_거절():
    with pytest.raises(ModeNotSupportedError):
        _searcher().search("방열 시트", "cite", "bm25", 3)


def test_조각에_벡터가_없으면_조용히_BM25만으로_섞지_않는다():
    chunks = [_chunk("D", 1, "방열 시트", [1.0, 0.0]), _chunk("D", 2, "방열 시트 구조", None)]
    with pytest.raises(ValueError, match="embedding"):
        _search(_searcher(chunks))
