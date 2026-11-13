import json

import numpy as np
import pytest

from src.rag.pipeline import LiveDenseRetriever, Pipeline, build_pipeline
from src.rag.settings import Settings
from src.retrieval.bm25 import whitespace_tokenizer
from src.retrieval.dense import DenseRetriever

CHUNKS = [
    {"chunk_id": "특허법#제1조", "text": "특허법 제1조(목적)\n발명 보호"},
    {"chunk_id": "특허법#제2조#제1항", "text": "특허법 제2조(정의)\n① 발명 정의"},
    {"chunk_id": "특허법#제2조#제2항", "text": "특허법 제2조(정의)\n② 특허 정의"},
    {"chunk_id": "특허법 시행령#제3조", "text": "특허법 시행령 제3조(기탁)\n미생물 기탁"},
    {"chunk_id": "특허법 시행규칙#제4조", "text": "특허법 시행규칙 제4조(서식)\n서식 제출"},
    {"chunk_id": "특허법#제5조", "text": "특허법 제5조(대리)\n대리인 선임"},
]
IDS = [c["chunk_id"] for c in CHUNKS]
MAT = np.array([[1, 0, 0], [0, 1, 0], [0, 1, 0.1], [0, 0, 1], [0.2, 0, 1], [0.5, 0.5, 0]], dtype=float)


def make(settings=None, expand=None, embed=None, rerank=None, chunks=CHUNKS, ids=IDS, mat=MAT):
    calls = {"expand": [], "embed": [], "rerank": []}

    def _expand(q):
        calls["expand"].append(q)
        return "발명, 기탁" if expand is None else expand(q)

    def _embed(q):
        calls["embed"].append(q)
        return [0, 0, 1] if embed is None else embed(q)

    def _rerank(q, ranked):
        calls["rerank"].append((q, list(ranked)))
        return (list(ranked), "순서 유지") if rerank is None else rerank(q, ranked)

    p = Pipeline(settings or Settings(), chunks, ids, mat, _expand, _embed, _rerank, tokenizer=whitespace_tokenizer)
    return p, calls


def test_retrieve_runs_expand_hybrid_rerank_and_builds_evidence():
    p, calls = make(rerank=lambda q, ranked: (list(reversed(ranked)), "뒤집음"))
    r = p.retrieve("미생물은 어디에 맡기나요?")
    assert r.expansion_raw == "발명, 기탁" and r.terms == ["발명", "기탁"]
    assert r.query == "미생물은 어디에 맡기나요?\n발명, 기탁"
    passed = calls["rerank"][0][1]
    assert r.ranked[0] == passed[-1]  # 가짜 재순위가 뒤집은 결과의 맨 앞
    assert [e.tag for e in r.evidence] == [f"E{i}" for i in range(1, len(r.evidence) + 1)]
    assert r.evidence[0].article_id == r.ranked[0] and r.rerank_raw == "뒤집음"
    assert len({e.article_id for e in r.evidence}) == len(r.evidence)  # 항 청크가 조문으로 묶임(제2조 한 번)
    assert calls["embed"] == [r.query]  # 임베딩은 확장된 질의로


def test_rerank_receives_original_question_not_expanded():
    p, calls = make()
    p.retrieve("원래 질문")
    assert calls["rerank"][0][0] == "원래 질문"


def test_evidence_text_joins_paragraphs_of_one_article():
    p, _ = make()
    r = p.retrieve("정의 발명 특허")
    art2 = next(e for e in r.evidence if e.article_id == "특허법#제2조")
    assert "① 발명 정의" in art2.text and "② 특허 정의" in art2.text


def test_retrieve_with_fewer_candidates_than_n():
    p, _ = make(chunks=CHUNKS[:2], ids=IDS[:2], mat=MAT[:2])
    assert 1 <= len(p.retrieve("발명").evidence) <= 2


@pytest.mark.parametrize("q", ["", "  \n"])
def test_blank_question_raises_before_any_call(q):
    p, calls = make()
    with pytest.raises(ValueError):
        p.retrieve(q)
    assert not any(calls.values())


def test_live_dense_matches_dense_retriever_ranking():
    vec = [0.3, 0.9, 0.1]
    live = LiveDenseRetriever(IDS, MAT, lambda q: vec)
    ref = DenseRetriever(IDS, MAT, {"q": np.array(vec)})
    assert [c for c, _ in live.search("q", top_n=4)] == [c for c, _ in ref.search("q", top_n=4)]


def test_build_pipeline_rejects_misaligned_embedding_ids(tmp_path):
    corpus = tmp_path / "c.jsonl"
    corpus.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in CHUNKS), encoding="utf-8")
    emb = tmp_path / "e.json"
    emb.write_text(json.dumps({"meta": {"model": "m"}, "ids": IDS[::-1], "vectors": MAT.tolist()}), encoding="utf-8")
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=x\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="순서"):
        build_pipeline(Settings(corpus=corpus, chunk_emb=emb, env_path=env))
