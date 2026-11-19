"""질의 벡터 만들기 명령 테스트 (#66). 가짜 임베딩 전송층만, 네트워크·키 없음."""

import json
import logging
from datetime import date

import pytest

from eval.retrieval.embed_queries import main
from eval.retrieval.gold import GoldItem, GoldRow
from patent_ai.core.llm.embed_transport import FakeEmbedTransport
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.retrieval.schemas import Edition

SECRET = "비밀스러운 거절이유 본문"


def _row(no, query):
    item = GoldItem(
        kind="article",
        start=290002,
        end=290002,
        label="제29조제2항",
        gold_edition=Edition(status="confirmed", effective_from=date(2020, 3, 11)),
    )
    return GoldRow(
        row_id=f"95:r{no}", corpus="law", query=query, as_of=date(2020, 4, 1), items=[item]
    )


@pytest.fixture
def files(tmp_path):
    (tmp_path / "t.yaml").write_text(
        "embed:\n  model: fake-embed-1\n  batch_size: 10\n", encoding="utf-8"
    )
    cfg = tmp_path / "idx.yaml"
    cfg.write_text("index_version: law-idx-v2\nembed_step: t.embed\n", encoding="utf-8")
    gold = tmp_path / "law_gold.jsonl"
    rows = [_row(1, SECRET), _row(2, "다른 질의"), _row(3, SECRET)]
    gold.write_text("".join(r.model_dump_json() + "\n" for r in rows), encoding="utf-8")
    return tmp_path, cfg, gold


def ctx_of(t):
    return RunContext("r", CallBudget(), MemoryRecorder(), t, None)


def args(cfg, gold, out):
    return ["--config", str(cfg), "--gold", str(gold), "--out", str(out)]


def test_질의마다_벡터_하나_같은_질의는_한_번_로그엔_원문_없음(files, caplog):
    d, cfg, gold = files
    out = d / "q" / "query_vectors.json"
    t = FakeEmbedTransport(lambda s: [float(len(s)), 1.0])
    with caplog.at_level(logging.INFO):
        assert main(args(cfg, gold, out), ctx=ctx_of(t), config_dir=d) == 0
    vecs = json.loads(out.read_text(encoding="utf-8"))
    assert set(vecs) == {SECRET, "다른 질의"}
    assert sorted(x for c in t.calls for x in c["texts"]) == sorted({SECRET, "다른 질의"})
    assert SECRET not in caplog.text and "질의 2개" in caplog.text


def test_정답_파일이_없거나_0줄이면_1로_끝나고_모델을_안_부른다(files):
    d, cfg, gold = files
    t = FakeEmbedTransport(lambda s: [1.0])
    assert main(args(cfg, d / "없음.jsonl", d / "a.json"), ctx=ctx_of(t), config_dir=d) == 1
    empty = d / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert main(args(cfg, empty, d / "b.json"), ctx=ctx_of(t), config_dir=d) == 1
    assert t.calls == []


def test_출력_파일이_있으면_돈_쓰기_전에_멈춘다(files):
    d, cfg, gold = files
    out = d / "query_vectors.json"
    out.write_text("{}", encoding="utf-8")
    t = FakeEmbedTransport(lambda s: [1.0])
    assert main(args(cfg, gold, out), ctx=ctx_of(t), config_dir=d) == 1
    assert t.calls == [] and out.read_text(encoding="utf-8") == "{}"


def test_out이_빠지면_인자_오류(files):
    d, cfg, gold = files
    with pytest.raises(SystemExit):
        main(["--config", str(cfg), "--gold", str(gold)])


def test_설정에_embed_step이_없으면_traceback_없이_1로_멈춘다(files, caplog):
    d, cfg, gold = files
    cfg.write_text("index_version: law-idx-v2\n", encoding="utf-8")
    t = FakeEmbedTransport(lambda s: [1.0])
    assert main(args(cfg, gold, d / "q.json"), ctx=ctx_of(t), config_dir=d) == 1
    assert t.calls == [] and "embed_step" in caplog.text
