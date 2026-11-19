"""embed(): 글 → 벡터 (가짜·기록 전송층만, 네트워크·API 키 없음). #66 A3."""

import logging

import pytest

from patent_ai.core.llm.cache import MemoryCache
from patent_ai.core.llm.embed import embed, load_embed_config, query_embedder
from patent_ai.core.llm.embed_transport import (
    EmbedResponse,
    FakeEmbedTransport,
    OpenAIEmbedTransport,
    RecordedEmbedTransport,
    parse_openai_embeddings,
    save_embed_recording,
)
from patent_ai.core.llm.errors import (
    ModelCallFailed,
    ModelCallLimitExceeded,
    ModelConfigError,
    ModelOutputInvalid,
    RecordingMissing,
)
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import TransportError

STEP = "t.embed"


def make_config(tmp_path, **extra):
    body = {"model": "fake-embed-1", "price_per_mtok_input": 0.02, "batch_size": 2, **extra}
    lines = "".join(f"  {k}: {v}\n" for k, v in body.items())
    (tmp_path / "t.yaml").write_text("embed:\n" + lines, encoding="utf-8")
    return tmp_path


def vec_of(text: str) -> list[float]:
    # 글마다 다른 지어낸 벡터 (길이 3)
    return [float(len(text)), float(ord(text[0])), 1.0]


def ctx_with(transport, cache=None, budget=None):
    return RunContext("run-1", budget or CallBudget(), MemoryRecorder(), transport, cache)


def test_입력_순서대로_벡터를_돌려주고_묶음_크기대로_나눠_부른다(tmp_path):
    cfg = make_config(tmp_path)
    t = FakeEmbedTransport(vec_of)
    ctx = ctx_with(t)
    out = embed(STEP, ["가나", "다", "라마바"], ctx=ctx, config_dir=cfg)
    assert out == [vec_of("가나"), vec_of("다"), vec_of("라마바")]
    assert [c["texts"] for c in t.calls] == [["가나", "다"], ["라마바"]]  # batch_size 2
    # 묶음 호출마다 기록 한 줄, 비용은 입력 토큰 × 가격
    assert [r.outcome for r in ctx.recorder.records] == ["ok", "ok"]
    assert all(r.cost is not None for r in ctx.recorder.records)


def test_캐시에_있는_글은_다시_안_부른다(tmp_path):
    cfg = make_config(tmp_path)
    c = MemoryCache()
    t = FakeEmbedTransport(vec_of)
    embed(STEP, ["가나", "다"], ctx=ctx_with(t, c), config_dir=cfg)
    t2 = FakeEmbedTransport(vec_of)
    out = embed(STEP, ["다", "새글", "가나"], ctx=ctx_with(t2, c), config_dir=cfg)
    assert out == [vec_of("다"), vec_of("새글"), vec_of("가나")]
    assert [c["texts"] for c in t2.calls] == [["새글"]]


def test_모델이_다르면_캐시를_같이_쓰지_않는다(tmp_path):
    c = MemoryCache()
    embed(
        STEP,
        ["가나"],
        ctx=ctx_with(FakeEmbedTransport(vec_of), c),
        config_dir=make_config(tmp_path),
    )
    other = tmp_path / "other"
    other.mkdir()
    t2 = FakeEmbedTransport(vec_of)
    embed(STEP, ["가나"], ctx=ctx_with(t2, c), config_dir=make_config(other, model="fake-embed-2"))
    assert len(t2.calls) == 1


def test_빈_목록이면_경고하고_빈_결과(tmp_path, caplog):
    t = FakeEmbedTransport(vec_of)
    with caplog.at_level(logging.WARNING):
        assert embed(STEP, [], ctx=ctx_with(t), config_dir=make_config(tmp_path)) == []
    assert t.calls == [] and "0개" in caplog.text


def test_호출_수_상한을_넘으면_멈춘다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=1)
    t = FakeEmbedTransport(vec_of)
    with pytest.raises(ModelCallLimitExceeded):
        embed(STEP, ["가", "나", "다"], ctx=ctx_with(t), config_dir=cfg)  # 묶음 2번 필요
    assert len(t.calls) == 1


def test_진짜_전송층인데_max_model_calls가_없으면_부르기_전에_멈춘다(tmp_path):
    inner = FakeEmbedTransport(vec_of)
    real = object.__new__(OpenAIEmbedTransport)
    real.embed = inner.embed
    with pytest.raises(ModelConfigError, match="max_model_calls"):
        embed(STEP, ["가나"], ctx=ctx_with(real, cache=False), config_dir=make_config(tmp_path))
    assert inner.calls == []


def test_진짜_전송층도_상한이_있으면_부르고_캐시_적중이면_상한_없어도_된다(tmp_path):
    inner = FakeEmbedTransport(vec_of)
    real = object.__new__(OpenAIEmbedTransport)
    real.embed = inner.embed
    c = MemoryCache()
    out = embed(
        STEP, ["가나"], ctx=ctx_with(real, c), config_dir=make_config(tmp_path, max_model_calls=3)
    )
    assert out == [vec_of("가나")]
    other = tmp_path / "nolimit"
    other.mkdir()
    again = embed(STEP, ["가나"], ctx=ctx_with(real, c), config_dir=make_config(other))
    assert again == [vec_of("가나")] and len(inner.calls) == 1


def test_다시_부를_만한_오류는_max_retries만큼_다시_부른다(tmp_path):
    cfg = make_config(tmp_path, max_retries=2)
    t = FakeEmbedTransport(vec_of, errors=[TransportError("429", True)])
    sleeps = []
    out = embed(STEP, ["가나"], ctx=ctx_with(t), config_dir=cfg, sleep=sleeps.append)
    assert out == [vec_of("가나")] and len(t.calls) == 2 and sleeps == [1.0]


def test_다시_부를_수_없는_오류는_바로_ModelCallFailed(tmp_path):
    cfg = make_config(tmp_path, max_retries=2)
    t = FakeEmbedTransport(vec_of, errors=[TransportError("400", False)])
    with pytest.raises(ModelCallFailed):
        embed(STEP, ["가나"], ctx=ctx_with(t), config_dir=cfg)
    assert len(t.calls) == 1


def test_벡터_길이가_서로_다르면_ModelOutputInvalid이고_캐시에_안_남는다(tmp_path):
    cfg = make_config(tmp_path, batch_size=5)
    c = MemoryCache()
    mixed = FakeEmbedTransport(lambda s: [1.0] if s == "다" else [1.0, 2.0])
    with pytest.raises(ModelOutputInvalid):
        embed(STEP, ["가나", "다"], ctx=ctx_with(mixed, c), config_dir=cfg)
    # 잘못된 벡터를 캐시에 남기면 다음 실행도 계속 실패한다
    good = FakeEmbedTransport(vec_of)
    assert embed(STEP, ["가나", "다"], ctx=ctx_with(good, c), config_dir=cfg)[1] == vec_of("다")


def test_길이_0_벡터면_ModelOutputInvalid(tmp_path):
    empty = FakeEmbedTransport(lambda s: [])
    with pytest.raises(ModelOutputInvalid):
        embed(STEP, ["가나"], ctx=ctx_with(empty), config_dir=make_config(tmp_path))


class _OneShort(FakeEmbedTransport):
    """글 수보다 벡터를 하나 덜 돌려주는 전송층."""

    def embed(self, *, step, model, texts):
        resp = super().embed(step=step, model=model, texts=texts)
        return EmbedResponse(resp.vectors[:-1], resp.input_tokens)


def test_벡터_개수가_글_수와_다르면_ModelOutputInvalid(tmp_path):
    with pytest.raises(ModelOutputInvalid, match="벡터 1개"):
        embed(STEP, ["가", "나"], ctx=ctx_with(_OneShort(vec_of)), config_dir=make_config(tmp_path))


def test_transport를_안_주고_상한이_없으면_SDK를_만들기_전에_멈춘다(tmp_path):
    # conftest의 '진짜 호출 막힘'(RuntimeError)이 아니라 설정 검사(ModelConfigError)에서 멈춰야 한다
    with pytest.raises(ModelConfigError, match="max_model_calls"):
        embed(STEP, ["가나"], ctx=ctx_with(None, cache=False), config_dir=make_config(tmp_path))


def test_진짜_전송층이면_기본_파일_캐시를_쓰고_가짜면_캐시를_안_쓴다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=5)
    inner = FakeEmbedTransport(vec_of)
    real = object.__new__(OpenAIEmbedTransport)
    real.embed = inner.embed
    embed(STEP, ["가나"], ctx=ctx_with(real), config_dir=cfg)  # cache None -> 기본 FileCache
    embed(STEP, ["가나"], ctx=ctx_with(real), config_dir=cfg)
    assert len(inner.calls) == 1
    fake = FakeEmbedTransport(vec_of)
    embed(STEP, ["가나"], ctx=ctx_with(fake), config_dir=cfg)
    embed(STEP, ["가나"], ctx=ctx_with(fake), config_dir=cfg)
    assert len(fake.calls) == 2


def test_기록_전송층은_저장한_벡터를_돌려주고_없으면_RecordingMissing(tmp_path):
    rec = tmp_path / "rec"
    save_embed_recording(rec, [1.0, 2.0], step=STEP, model="fake-embed-1", text="가나")
    t = RecordedEmbedTransport(rec)
    cfg = make_config(tmp_path)
    assert embed(STEP, ["가나"], ctx=ctx_with(t), config_dir=cfg) == [[1.0, 2.0]]
    with pytest.raises(RecordingMissing):
        embed(STEP, ["없는 글"], ctx=ctx_with(t), config_dir=cfg)
    with pytest.raises(FileExistsError):  # 덮어쓰지 않는다
        save_embed_recording(rec, [9.0], step=STEP, model="fake-embed-1", text="가나")


def test_질의_하나를_벡터로_바꾸는_함수(tmp_path):
    f = query_embedder(STEP, ctx_with(FakeEmbedTransport(vec_of)), config_dir=make_config(tmp_path))
    assert f("가나") == vec_of("가나")


def test_설정_검사(tmp_path, caplog):
    with pytest.raises(ModelConfigError):  # model 없음
        (tmp_path / "t.yaml").write_text("embed:\n  batch_size: 2\n", encoding="utf-8")
        load_embed_config(STEP, tmp_path)
    (tmp_path / "t.yaml").write_text("embed:\n  model: m\n  batch_size: 0\n", encoding="utf-8")
    with pytest.raises(ModelConfigError):  # 묶음 크기 0
        load_embed_config(STEP, tmp_path)
    (tmp_path / "t.yaml").write_text("embed:\n  model: m\n  batchsize: 3\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        cfg = load_embed_config(STEP, tmp_path)
    assert "batchsize" in caplog.text and cfg.batch_size == 100  # 기본값


def test_OpenAI_응답은_index_순서로_읽는다():
    class D:
        def __init__(self, i, v):
            self.index, self.embedding = i, v

    class U:
        prompt_tokens = 7

    class R:
        data = [D(1, [2.0]), D(0, [1.0])]
        usage = U()

    assert parse_openai_embeddings(R()) == EmbedResponse([[1.0], [2.0]], 7)


def test_진짜_임베딩_전송층은_테스트에서_만들_수_없다():
    with pytest.raises(RuntimeError, match="진짜 호출 막힘"):
        OpenAIEmbedTransport()
