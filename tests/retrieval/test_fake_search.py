"""fake 구현 테스트. 모두 get_searcher("fake", ...)로 CheckedSearcher를 거친다 (task-4)."""

import json
from datetime import date
from pathlib import Path

import pytest

import patent_ai.retrieval  # noqa: F401  (fake 등록)
from patent_ai.retrieval import get_searcher
from patent_ai.retrieval.errors import RecordedEmbeddingMissing
from patent_ai.retrieval.repository import InMemoryChunkRepository

FIX = Path(__file__).parent.parent / "fixtures" / "retrieval"
QV = str(FIX / "query_vectors.json")
KR = "KR1000000001A"
US = "US0000001B2"


def cite(extra=None):
    repo = InMemoryChunkRepository.from_jsonl("cite", FIX / "chunks_cite.jsonl")
    s = {"index_version": "cite-idx-v1", "query_vectors": QV, **(extra or {})}
    return get_searcher("fake", repo, s)


def law():
    repo = InMemoryChunkRepository.from_jsonl("law", FIX / "chunks_law.jsonl")
    return get_searcher("fake", repo, {"index_version": "law-idx-v1", "query_vectors": QV})


def ids(res):
    return [h.chunk_id.split(":", 2)[2] for h in res.hits]


def test_데모_한_공보_안_상위_k():
    repo = InMemoryChunkRepository.from_jsonl("cite", FIX / "chunks_cite.jsonl")
    s = get_searcher("fake", repo, {"index_version": "cite-idx-v1"})
    res = s.search("기판 가열", "cite", "bm25", 3, doc_ids=[KR])
    assert {h.doc_id for h in res.hits} == {KR}
    assert [h.rank for h in res.hits] == [1, 2, 3]
    assert res.status is None


def test_bm25_같은_점수는_chunk_id_오름차순():
    res = cite().search("기판 가열", "cite", "bm25", 3, doc_ids=[KR])
    assert ids(res) == ["[0001]", "[0002]", "[0003]"]
    assert [h.score for h in res.hits] == [2, 2, 2]


def test_bm25_한_공보_안만():
    res = cite().search("칼럼 조각", "cite", "bm25", 5, doc_ids=[US])
    assert ids(res) == ["3:10-25", "3:25-40", "4:5-20"]


def test_vector_상위_k는_코사인_순():
    res = cite().search("열 처리", "cite", "vector", 3, doc_ids=[KR])
    assert ids(res) == ["요약", "청구항 1", "[0010]"]
    assert res.hits[0].score == pytest.approx(1.0)


def test_vector_점수_0_이하는_뺀다():
    res = cite().search("도면", "cite", "vector", 5, doc_ids=[KR])
    assert ids(res) == ["도 1"]


def test_기준일_거르기와_판본모름_센다():
    res = law().search("진보성 판단", "law", "bm25", 5, as_of=date(2021, 1, 1))
    assert len(res.hits) == 1 and "신판" in res.hits[0].chunk_id
    assert res.skipped_unverified_edition == 1


def test_기준일_없으면_판본_거르지_않고_센것_0():
    res = law().search("진보성 판단", "law", "bm25", 5)
    assert [h.chunk_id[-4:] for h in res.hits] == ["(구판)", "(신판)"]
    assert res.skipped_unverified_edition == 0


def test_겹치는_낱말_없으면_not_found_in_scope와_scope():
    res = cite().search("없는낱말", "cite", "bm25", 3, doc_ids=[KR])
    assert res.hits == []
    assert res.status == "not_found_in_scope"
    assert res.status_reason is None
    assert res.scope.doc_ids == [KR] and res.scope.k == 3
    # 찾아본 범위: 말뭉치·색인 판·거를 문헌·기준일
    assert res.corpus == "cite" and res.index_version == "cite-idx-v1"
    assert res.scope.as_of is None


def test_기준일로_다_빠지면_not_found_in_scope와_판본모름_셈():
    # 2010년엔 시행 중인 판본이 없다 → 없음이 아니라 "조회 범위 내 없음"
    res = law().search("진보성 판단", "law", "bm25", 5, as_of=date(2010, 1, 1))
    assert res.hits == []
    assert res.status == "not_found_in_scope"
    assert res.scope.as_of == date(2010, 1, 1)
    assert res.corpus == "law" and res.index_version == "law-idx-v1"
    assert res.skipped_unverified_edition == 1


def test_없는_공보는_unverified_text_missing():
    res = cite().search("기판", "cite", "bm25", 3, doc_ids=["KR9999999999A"])
    assert res.status == "unverified"
    assert res.status_reason == "text_missing"


def test_녹화_없는_질의는_RecordedEmbeddingMissing():
    with pytest.raises(RecordedEmbeddingMissing):
        cite().search("녹화에 없는 질의", "cite", "vector", 3)


def test_vector인데_query_vectors_설정_없으면_ValueError():
    repo = InMemoryChunkRepository.from_jsonl("cite", FIX / "chunks_cite.jsonl")
    s = get_searcher("fake", repo, {"index_version": "cite-idx-v1"})
    with pytest.raises(ValueError, match="query_vectors"):
        s.search("열 처리", "cite", "vector", 3)


def test_vector인데_조각에_embedding_없으면_ValueError(tmp_path):
    row = json.loads((FIX / "chunks_cite.jsonl").read_text(encoding="utf-8").splitlines()[0])
    row.pop("embedding")
    p = tmp_path / "c.jsonl"
    p.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    repo = InMemoryChunkRepository.from_jsonl("cite", p)
    s = get_searcher("fake", repo, {"index_version": "cite-idx-v1", "query_vectors": QV})
    with pytest.raises(ValueError, match="embedding"):
        s.search("열 처리", "cite", "vector", 3)
