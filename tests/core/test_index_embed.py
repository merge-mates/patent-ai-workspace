"""색인에 벡터 채우기 테스트 (#66 B1). 가짜 임베딩 전송층만, 네트워크·키 없음."""

import json
from datetime import date

import pytest

from patent_ai.core.index_embed import (
    IndexEmbedError,
    embed_chunks,
    embed_queries,
    main,
    write_query_vectors,
)
from patent_ai.core.llm.embed_transport import FakeEmbedTransport
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.retrieval.law_index import write_jsonl
from patent_ai.retrieval.repository import InMemoryChunkRepository
from patent_ai.retrieval.schemas import Chunk, Edition, Location

STEP = "t.embed"
ED = Edition(status="confirmed", effective_from=date(2020, 3, 11), label="특허법_1_20200311")


def _chunk(doc, loc, text, version="law-idx-v1"):
    return Chunk(
        chunk_id=f"{version}:{doc}:{loc}",
        index_version=version,
        doc_id=doc,
        chunk_kind="article",
        location=Location(kind="article", start=loc, end=loc, label=f"제{loc}조"),
        edition=ED,
        text=text,
    )


def vec_of(text):
    return [float(len(text)), 1.0]


@pytest.fixture
def cfg(tmp_path):
    (tmp_path / "t.yaml").write_text(
        "embed:\n  model: fake-embed-1\n  batch_size: 2\n  price_per_mtok_input: 0.02\n",
        encoding="utf-8",
    )
    return tmp_path


def ctx_of(t):
    return RunContext("run-1", CallBudget(), MemoryRecorder(), t, None)


V1 = [
    _chunk("특허법_1_20200311", 290002, "제29조 ② 쉽게 발명"),
    _chunk("특허법_2_20201020", 290002, "제29조 ② 쉽게 발명"),  # 다른 판, 같은 글
    _chunk("특허법_2_20201020", 420004, "제42조 ④ 명확"),
]


def test_v2는_글_위치_판본이_v1과_같고_판_이름과_벡터만_다르다(cfg):
    t = FakeEmbedTransport(vec_of)
    out = embed_chunks(V1, "law-idx-v2", STEP, ctx_of(t), cfg)
    assert [c.chunk_id for c in out] == [
        "law-idx-v2:특허법_1_20200311:290002",
        "law-idx-v2:특허법_2_20201020:290002",
        "law-idx-v2:특허법_2_20201020:420004",
    ]
    for old, new in zip(V1, out, strict=True):
        assert new.index_version == "law-idx-v2"
        assert (new.text, new.location, new.edition, new.doc_id) == (
            old.text,
            old.location,
            old.edition,
            old.doc_id,
        )
        assert new.embedding == vec_of(old.text)


def test_같은_글은_한_번만_임베딩한다(cfg):
    t = FakeEmbedTransport(vec_of)
    embed_chunks(V1, "law-idx-v2", STEP, ctx_of(t), cfg)
    sent = [text for call in t.calls for text in call["texts"]]
    assert sorted(sent) == sorted({c.text for c in V1})  # 3조각, 글 2개


def test_같은_입력이면_같은_바이트이고_저장소가_읽는다(cfg, tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    write_jsonl(embed_chunks(V1, "law-idx-v2", STEP, ctx_of(FakeEmbedTransport(vec_of)), cfg), a)
    write_jsonl(embed_chunks(V1, "law-idx-v2", STEP, ctx_of(FakeEmbedTransport(vec_of)), cfg), b)
    assert a.read_bytes() == b.read_bytes()
    repo = InMemoryChunkRepository.from_jsonl("law", a)
    assert all(c.embedding for c in repo.chunks("law", "law-idx-v2", None, None))


def test_판_이름이_틀리거나_섞이거나_비면_멈춘다(cfg):
    t = FakeEmbedTransport(vec_of)
    with pytest.raises(IndexEmbedError):
        embed_chunks(V1, "law-idx-v1", STEP, ctx_of(t), cfg)  # 같은 판으로는 안 만든다
    with pytest.raises(IndexEmbedError):
        embed_chunks(V1, "cite-idx-v2", STEP, ctx_of(t), cfg)  # 말뭉치가 다름
    with pytest.raises(IndexEmbedError):
        embed_chunks(V1 + [_chunk("x", 1, "가", "law-idx-v3")], "law-idx-v2", STEP, ctx_of(t), cfg)
    with pytest.raises(IndexEmbedError):
        embed_chunks([], "law-idx-v2", STEP, ctx_of(t), cfg)
    assert t.calls == []  # 검사에서 먼저 멈춤


def test_질의_벡터는_질의마다_하나이고_같은_질의는_한_번만(cfg):
    t = FakeEmbedTransport(vec_of)
    vecs = embed_queries(["가나", "다", "가나"], STEP, ctx_of(t), cfg)
    assert vecs == {"가나": vec_of("가나"), "다": vec_of("다")}
    assert sorted(x for c in t.calls for x in c["texts"]) == ["가나", "다"]


def test_질의_벡터_파일은_덮어쓰지_않는다(tmp_path):
    out = tmp_path / "q" / "query_vectors.json"
    write_query_vectors({"가나": [1.0]}, out)
    assert json.loads(out.read_text(encoding="utf-8")) == {"가나": [1.0]}
    with pytest.raises(IndexEmbedError):
        write_query_vectors({"가나": [2.0]}, out)


def test_chunk_id_앞말이_판과_다르면_멈춘다(cfg):
    odd = _chunk("d", 1, "가").model_copy(update={"chunk_id": "엉뚱:d:1"})
    t = FakeEmbedTransport(vec_of)
    with pytest.raises(IndexEmbedError, match="시작하지 않는"):
        embed_chunks([odd], "law-idx-v2", STEP, ctx_of(t), cfg)
    assert t.calls == []


def _idx_files(tmp_path):
    src = tmp_path / "v1.jsonl"
    write_jsonl(V1, src)
    conf = tmp_path / "idx.yaml"
    out = tmp_path / "v2.jsonl"
    conf.write_text(
        f"index_version: law-idx-v2\nfrom: {src}\nembed_step: {STEP}\nout: {out}\n",
        encoding="utf-8",
    )
    return conf, out


def test_chunks_명령은_v2_파일을_만들고_0으로_끝난다(cfg, tmp_path):
    conf, out = _idx_files(tmp_path)
    assert (
        main(
            ["chunks", "--config", str(conf)],
            ctx=ctx_of(FakeEmbedTransport(vec_of)),
            config_dir=cfg,
        )
        == 0
    )
    repo = InMemoryChunkRepository.from_jsonl("law", out)
    assert repo.count_chunks("law", "law-idx-v2") == 3


def test_chunks_명령은_출력_파일이_있으면_돈_쓰기_전에_1로_멈춘다(cfg, tmp_path):
    conf, out = _idx_files(tmp_path)
    out.write_text("old", encoding="utf-8")
    t = FakeEmbedTransport(vec_of)
    assert main(["chunks", "--config", str(conf)], ctx=ctx_of(t), config_dir=cfg) == 1
    assert t.calls == [] and out.read_text(encoding="utf-8") == "old"


@pytest.mark.parametrize("missing", ["out", "from", "embed_step", "index_version"])
def test_chunks_명령은_설정_키가_빠지면_traceback_없이_1로_멈춘다(cfg, tmp_path, missing, caplog):
    conf, _ = _idx_files(tmp_path)
    lines = conf.read_text(encoding="utf-8").splitlines()
    conf.write_text(
        "\n".join(x for x in lines if not x.startswith(missing + ":")), encoding="utf-8"
    )
    t = FakeEmbedTransport(vec_of)
    assert main(["chunks", "--config", str(conf)], ctx=ctx_of(t), config_dir=cfg) == 1
    assert t.calls == [] and missing in caplog.text
