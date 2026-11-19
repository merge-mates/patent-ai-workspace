"""vector 검색기 테스트 (#66 B2). 메모리 저장소 + 지어낸 벡터, 네트워크 없음."""

import json
import math
from datetime import date

import pytest

from patent_ai.retrieval.contract import get_searcher
from patent_ai.retrieval.errors import ModeNotSupportedError, RecordedEmbeddingMissing
from patent_ai.retrieval.repository import InMemoryChunkRepository
from patent_ai.retrieval.schemas import Chunk, Edition, Location

V = "law-idx-v2"
OLD = Edition(status="confirmed", effective_from=date(2020, 3, 11), effective_to=date(2020, 10, 19))
NEW = Edition(status="confirmed", effective_from=date(2020, 10, 20))


def _chunk(doc_id, loc, emb, edition=NEW):
    return Chunk(
        chunk_id=f"{V}:{doc_id}:{loc}",
        index_version=V,
        doc_id=doc_id,
        chunk_kind="article",
        location=Location(kind="article", start=loc, end=loc, label=str(loc)),
        edition=edition,
        text="글",
        embedding=emb,
    )


def _searcher(chunks, embed=None, **settings):
    repo = InMemoryChunkRepository({"law": chunks})
    return get_searcher("vector", repo, {"index_version": V, **settings}, embed)


def fixed(vec):
    return lambda q: vec


def test_코사인이_큰_순서로_k개():
    chunks = [_chunk("d", 1, [1.0, 0.0]), _chunk("d", 2, [0.6, 0.8]), _chunk("d", 3, [0.0, 1.0])]
    res = _searcher(chunks, fixed([1.0, 0.0])).search("q", "law", "vector", k=2)
    assert [h.location.start for h in res.hits] == [1, 2]
    assert res.hits[0].score == pytest.approx(1.0)
    assert res.hits[1].score == pytest.approx(0.6)
    assert [h.rank for h in res.hits] == [1, 2]
    assert res.hits[0].embedding is not None  # 조각 칸은 그대로 (결과 JSON에서만 빠짐)


def test_같은_점수면_chunk_id_순서():
    chunks = [_chunk("b", 1, [1.0, 0.0]), _chunk("a", 1, [2.0, 0.0])]
    res = _searcher(chunks, fixed([1.0, 0.0])).search("q", "law", "vector", k=5)
    assert [h.doc_id for h in res.hits] == ["a", "b"]


def test_기준일에_효력_있는_판만_나오고_판본_모름은_센다():
    chunks = [
        _chunk("old", 1, [1.0, 0.0], OLD),
        _chunk("new", 1, [1.0, 0.0], NEW),
        _chunk("unk", 1, [1.0, 0.0], Edition(status="unverified")),
    ]
    res = _searcher(chunks, fixed([1.0, 0.0])).search(
        "q", "law", "vector", 5, as_of=date(2020, 8, 1)
    )
    assert [h.doc_id for h in res.hits] == ["old"]
    assert res.skipped_unverified_edition == 1


def test_조각에_벡터가_없으면_조용히_빼지_않고_멈춘다():
    chunks = [_chunk("d", 1, [1.0, 0.0]), _chunk("d", 2, None)]
    with pytest.raises(ValueError, match="embedding"):
        _searcher(chunks, fixed([1.0, 0.0])).search("q", "law", "vector", 5)


def test_벡터_길이가_다르면_멈춘다():
    with pytest.raises(ValueError, match="차원"):
        _searcher([_chunk("d", 1, [1.0, 0.0])], fixed([1.0, 0.0, 0.0])).search(
            "q", "law", "vector", 5
        )


def test_질의_벡터는_설정의_기록_파일로도_받는다(tmp_path):
    path = tmp_path / "query_vectors.json"
    path.write_text(json.dumps({"q": [0.0, 1.0]}), encoding="utf-8")
    chunks = [_chunk("d", 1, [1.0, 0.0]), _chunk("d", 2, [0.0, 1.0])]
    s = _searcher(chunks, query_vectors=str(path))
    assert s.search("q", "law", "vector", 1).hits[0].location.start == 2
    with pytest.raises(RecordedEmbeddingMissing):
        s.search("없는 질의", "law", "vector", 1)


def test_질의_벡터를_받을_길이_없으면_멈춘다():
    with pytest.raises(ValueError, match="embed"):
        _searcher([_chunk("d", 1, [1.0, 0.0])]).search("q", "law", "vector", 1)


def test_고른_문서에_조각이_없으면_본문_없음():
    res = _searcher([_chunk("d", 1, [1.0, 0.0])], fixed([1.0, 0.0])).search(
        "q", "law", "vector", 5, doc_ids=["zz"]
    )
    assert res.status == "unverified" and res.status_reason == "body_missing"


def test_bm25_요청은_이_구현이_안_한다():
    with pytest.raises(ModeNotSupportedError):
        _searcher([_chunk("d", 1, [1.0, 0.0])], fixed([1.0, 0.0])).search("q", "law", "bm25", 5)


def test_길이_0_질의_벡터는_비슷함_0():
    res = _searcher([_chunk("d", 1, [1.0, 0.0])], fixed([0.0, 0.0])).search("q", "law", "vector", 5)
    assert math.isclose(res.hits[0].score, 0.0)
