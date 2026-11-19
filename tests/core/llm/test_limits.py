"""task-3: 호출 상한·전송 오류 재시도·호출 기록 (가짜 전송층만, 네트워크·API 키 없음)."""

import logging
from pathlib import Path

import anthropic
import httpx
import pytest
from pydantic import BaseModel

from patent_ai.core.llm.cache import MemoryCache
from patent_ai.core.llm.client import call_model
from patent_ai.core.llm.errors import (
    ModelCallFailed,
    ModelCallLimitExceeded,
    ModelConfigError,
    ModelOutputInvalid,
)
from patent_ai.core.llm.limits import CallBudget, CallRecord, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import (
    AnthropicTransport,
    FakeTransport,
    TransportError,
    TransportResponse,
)

FIX = Path(__file__).parent.parent.parent / "fixtures" / "llm"
VARS = {"lines": 2, "text": "청구항 1은 진보성이 없다"}
OK = TransportResponse("답", 600, 100)


def scripted(*items):
    """FakeTransport: 항목이 여럿이면 시도마다 차례로, 하나면 늘 같은 것 (답 또는 예외)."""
    return FakeTransport({"t.s": list(items) if len(items) > 1 else items[0]})


def make_config(tmp_path, **limits):
    """설정 파일을 임시 폴더에 만든다 (limits 칸을 단계 설정에 붙임)."""
    extra = "".join(f"  {k}: {v}\n" for k, v in limits.items())
    (tmp_path / "t.yaml").write_text(
        "s:\n  model: fake-model-1\n  effort: medium\n  max_tokens: 256\n"
        "  prompt: prompts/summarize.txt\n"
        "  price_per_mtok_input: 3.0\n  price_per_mtok_output: 15.0\n" + extra,
        encoding="utf-8",
    )
    return tmp_path


def run(
    transport,
    cfg,
    budget,
    recorder,
    run_id="run-1",
    cache=None,
    variables=VARS,
    sleeps=None,
    schema=None,
    attempt=1,
):
    return call_model(
        "t.s",
        variables,
        schema,
        run_id,
        attempt,
        transport=transport,
        cache=cache,
        config_dir=cfg,
        root=FIX,
        budget=budget,
        recorder=recorder,
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
    )


def test_평소_상한_안이면_성공하고_기록이_한_줄_남는다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=3)
    rec = MemoryRecorder()
    run(scripted(OK), cfg, CallBudget(), rec)
    assert len(rec.records) == 1
    r = rec.records[0]
    assert (r.run_id, r.step, r.model) == ("run-1", "t.s", "fake-model-1")
    assert (r.input_tokens, r.output_tokens) == (600, 100)
    assert r.cost == pytest.approx(600 * 3 / 1e6 + 100 * 15 / 1e6)
    assert r.elapsed_ms >= 0
    assert (r.from_cache, r.attempt, r.outcome) == (False, 1, "ok")


def test_경계_딱_상한만큼은_성공한다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=2)
    budget, rec, t = CallBudget(), MemoryRecorder(), scripted(OK)
    run(t, cfg, budget, rec)
    run(t, cfg, budget, rec)
    assert len(t.calls) == 2
    assert [r.outcome for r in rec.records] == ["ok", "ok"]


def test_상한_더하기_하나는_예외이고_전송층을_부르지_않는다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=2)
    budget, rec, t = CallBudget(), MemoryRecorder(), scripted(OK)
    run(t, cfg, budget, rec)
    run(t, cfg, budget, rec)
    with pytest.raises(ModelCallLimitExceeded) as e:
        run(t, cfg, budget, rec)
    assert e.value.limit == "max_model_calls"
    assert e.value.used == 2
    assert e.value.limit_value == 2
    assert len(t.calls) == 2  # 세 번째는 전송층까지 가지 않음
    assert rec.records[-1].outcome == "limit_exceeded"


def test_다른_run_id는_따로_센다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=1)
    budget, rec, t = CallBudget(), MemoryRecorder(), scripted(OK)
    run(t, cfg, budget, rec, run_id="a")
    run(t, cfg, budget, rec, run_id="b")
    with pytest.raises(ModelCallLimitExceeded):
        run(t, cfg, budget, rec, run_id="a")


def test_입력_토큰_상한은_쓴_양이_상한에_닿으면_다음_호출을_막는다(tmp_path):
    cfg = make_config(tmp_path, max_input_tokens=1000)
    budget, rec, t = CallBudget(), MemoryRecorder(), scripted(OK)  # 호출당 600
    run(t, cfg, budget, rec)  # 쓴 양 0 -> 600
    run(t, cfg, budget, rec)  # 600 < 1000 -> 1200
    with pytest.raises(ModelCallLimitExceeded) as e:
        run(t, cfg, budget, rec)
    assert e.value.limit == "max_input_tokens"
    assert e.value.used == 1200
    assert len(t.calls) == 2


def test_캐시_적중은_상한에_세지_않고_기록은_남는다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=1)
    budget, rec, t = CallBudget(), MemoryRecorder(), scripted(OK)
    cache = MemoryCache()
    run(t, cfg, budget, rec, cache=cache)
    run(t, cfg, budget, rec, cache=cache)
    run(t, cfg, budget, rec, cache=cache)
    assert len(t.calls) == 1
    assert [(r.from_cache, r.outcome) for r in rec.records] == [
        (False, "ok"),
        (True, "cache_hit"),
        (True, "cache_hit"),
    ]
    assert rec.records[1].cost == 0.0


def test_상한이_설정에_없으면_막지_않고_경고를_한_번만_남긴다(tmp_path, caplog):
    cfg = make_config(tmp_path)
    budget, rec, t = CallBudget(), MemoryRecorder(), scripted(OK)
    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            run(t, cfg, budget, rec)
    assert len(t.calls) == 5
    warns = [m for m in caplog.messages if "상한" in m]
    assert len(warns) == 1


def test_429가_계속되면_max_retries_뒤_ModelCallFailed(tmp_path):
    cfg = make_config(tmp_path, max_retries=2)
    rec, sleeps = MemoryRecorder(), []
    t = scripted(TransportError("429 너무 많은 요청", retryable=True))
    with pytest.raises(ModelCallFailed) as e:
        run(t, cfg, CallBudget(), rec, sleeps=sleeps)
    assert "429" in str(e.value)
    assert len(t.calls) == 3  # 처음 1 + 다시 2
    assert len(sleeps) == 2  # 다시 부르기 전에만 쉰다
    assert [r.outcome for r in rec.records] == ["transport_error"] * 3


def test_429_뒤_성공하면_결과를_돌려준다(tmp_path):
    cfg = make_config(tmp_path, max_retries=2)
    rec = MemoryRecorder()
    t = scripted(TransportError("429", retryable=True), OK)
    r = run(t, cfg, CallBudget(), rec)
    assert r.text == "답"
    assert [x.outcome for x in rec.records] == ["transport_error", "ok"]


def test_max_retries가_없으면_다시_부르지_않는다(tmp_path):
    cfg = make_config(tmp_path)
    t = scripted(TransportError("연결 끊김", retryable=True))
    with pytest.raises(ModelCallFailed):
        run(t, cfg, CallBudget(), MemoryRecorder())
    assert len(t.calls) == 1


def test_다시_불러도_소용없는_오류는_바로_실패한다(tmp_path):
    cfg = make_config(tmp_path, max_retries=3)
    t = scripted(TransportError("400 잘못된 요청", retryable=False))
    with pytest.raises(ModelCallFailed):
        run(t, cfg, CallBudget(), MemoryRecorder())
    assert len(t.calls) == 1


def test_다시_부르는_것도_호출_수에_센다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=2, max_retries=5)
    t = scripted(TransportError("429", retryable=True))
    with pytest.raises(ModelCallLimitExceeded) as e:
        run(t, cfg, CallBudget(), MemoryRecorder())
    assert e.value.used == 2
    assert len(t.calls) == 2


class Strict(BaseModel):
    title: str


def test_검사_실패_재시도도_상한에_센다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=1)
    budget, rec = CallBudget(), MemoryRecorder()
    t = scripted(TransportResponse("{}", 10, 1))
    with pytest.raises(ModelOutputInvalid):
        run(t, cfg, budget, rec, schema=Strict, attempt=1)
    with pytest.raises(ModelCallLimitExceeded):
        run(t, cfg, budget, rec, schema=Strict, attempt=2)
    assert len(t.calls) == 1
    assert [r.outcome for r in rec.records] == ["invalid_output", "limit_exceeded"]


def test_budget이_없으면_가짜_전송층이어도_막는다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=1)
    for transport in (None, scripted(OK)):
        with pytest.raises(ModelConfigError, match="CallBudget"):
            call_model("t.s", VARS, None, "run-1", transport=transport, config_dir=cfg, root=FIX)


def test_recorder가_없으면_기록_빠짐_경고를_단계마다_한_번(tmp_path, caplog):
    cfg = make_config(tmp_path, max_model_calls=9)
    budget, t = CallBudget(), scripted(OK)
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            run(t, cfg, budget, None, run_id="run-norec-unique")
    warns = [m for m in caplog.messages if "기록" in m]
    assert len(warns) == 1


def test_TransportError가_아닌_예외도_기록하고_세고_ModelCallFailed로_감싼다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=1, max_retries=3)
    budget, rec = CallBudget(), MemoryRecorder()
    t = scripted(RuntimeError("뜻밖의 오류"))
    with pytest.raises(ModelCallFailed, match="뜻밖의 오류"):
        run(t, cfg, budget, rec)
    assert len(t.calls) == 1  # 모르는 오류는 다시 부르지 않는다
    assert [r.outcome for r in rec.records] == ["transport_error"]
    with pytest.raises(ModelCallLimitExceeded):  # 호출 수에 셌다
        run(t, cfg, budget, rec)


def test_재시도_기록에_전송_시도_번호가_남는다(tmp_path):
    cfg = make_config(tmp_path, max_retries=2)
    rec = MemoryRecorder()
    t = scripted(TransportError("429", retryable=True), OK)
    run(t, cfg, CallBudget(), rec)
    assert [r.transport_try for r in rec.records] == [1, 2]
    cached = MemoryRecorder()
    cache = MemoryCache()
    run(scripted(OK), cfg, CallBudget(), cached, cache=cache)
    run(scripted(OK), cfg, CallBudget(), cached, cache=cache)
    assert [r.transport_try for r in cached.records] == [1, 0]  # 적중은 0


# ---- AnthropicTransport: SDK 예외 -> TransportError (네트워크 없음) ----
_REQ = httpx.Request("POST", "https://example.invalid/v1/messages")


class _Raises:
    def __init__(self, exc):
        self.messages = self
        self.exc = exc

    def create(self, **kwargs):
        raise self.exc


def _sdk_transport(exc):
    # conftest가 __init__을 막으므로 객체만 만들고 가짜 클라이언트를 넣는다
    tr = object.__new__(AnthropicTransport)
    tr._client = _Raises(exc)
    return tr


def _status_error(code):
    resp = httpx.Response(code, request=_REQ)
    return anthropic.APIStatusError(f"에러 {code}", response=resp, body=None)


@pytest.mark.parametrize(
    "exc,retryable",
    [
        (_status_error(429), True),
        (_status_error(500), True),
        (_status_error(401), False),
        (anthropic.APIConnectionError(request=_REQ), True),
    ],
)
def test_SDK_예외를_TransportError로_바꾸고_다시_부를지_정한다(exc, retryable):
    tr = _sdk_transport(exc)
    with pytest.raises(TransportError) as e:
        tr.complete(step="t.s", model="m", prompt="p", effort="medium", max_tokens=5)
    assert e.value.retryable is retryable


# ---- RunContext ----
def ctx_call(ctx, cfg, attempt=1, schema=None, **extra):
    return call_model(
        "t.s", VARS, schema, attempt=attempt, ctx=ctx, config_dir=cfg, root=FIX, **extra
    )


def test_ctx로_부르면_ctx의_run_id_budget_recorder_transport를_쓴다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=1)
    rec = MemoryRecorder()
    ctx = RunContext("run-ctx", CallBudget(), rec, transport=scripted(OK))
    ctx_call(ctx, cfg)
    assert [(r.run_id, r.outcome) for r in rec.records] == [("run-ctx", "ok")]
    with pytest.raises(ModelCallLimitExceeded):
        ctx_call(ctx, cfg)  # 같은 ctx 안에서 상한이 쌓인다


def test_ctx_경로에서도_attempt_1_2_둘_다_센다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=1)
    ctx = RunContext("run-ctx", CallBudget(), MemoryRecorder(), transport=scripted(OK))
    ctx_call(ctx, cfg, attempt=1)
    with pytest.raises(ModelCallLimitExceeded):
        ctx_call(ctx, cfg, attempt=2)


def test_ctx와_따로_넘긴_인자를_같이_주면_막는다(tmp_path):
    cfg = make_config(tmp_path)
    ctx = RunContext("run-ctx", CallBudget(), MemoryRecorder(), transport=scripted(OK))
    with pytest.raises(ModelConfigError, match="ctx"):
        ctx_call(ctx, cfg, budget=CallBudget())
    with pytest.raises(ModelConfigError, match="ctx"):
        call_model("t.s", VARS, None, "run-x", ctx=ctx, config_dir=cfg, root=FIX)


def test_가짜_전송층이면_캐시_기본은_안_쓰고_진짜_전송층이면_파일_캐시를_쓴다(tmp_path):
    cfg = make_config(tmp_path)
    fake = scripted(OK)
    ctx = RunContext("r", CallBudget(), MemoryRecorder(), transport=fake)
    ctx_call(ctx, cfg)
    ctx_call(ctx, cfg)
    assert len(fake.calls) == 2  # cache None + Fake -> 캐시 안 씀

    # AnthropicTransport 객체(생성자 우회, complete는 가짜로 바꿈)면 기본 FileCache
    inner = scripted(OK)
    real = object.__new__(AnthropicTransport)
    real.complete = inner.complete
    ctx2 = RunContext("r2", CallBudget(), MemoryRecorder(), transport=real)
    ctx_call(ctx2, cfg)
    r = ctx_call(ctx2, cfg)
    assert r.from_cache is True
    assert len(inner.calls) == 1


# ---- FakeTransport 답 목록 ----
def test_FakeTransport는_목록이면_시도마다_차례로_답한다():
    t = FakeTransport({"s": [TransportResponse("a", 1, 1), TransportError("x", True)]})
    kw = dict(step="s", model="m", prompt="p", effort="medium", max_tokens=1)
    assert t.complete(**kw).text == "a"
    with pytest.raises(TransportError):
        t.complete(**kw)
    with pytest.raises(ModelConfigError):  # 목록을 다 씀
        t.complete(**kw)


def test_FakeTransport에_없는_step이면_ModelConfigError이고_감싸지_않는다(tmp_path):
    cfg = make_config(tmp_path, max_retries=3)
    with pytest.raises(ModelConfigError):
        run(FakeTransport({}), cfg, CallBudget(), MemoryRecorder())


def test_기록기는_CallRecord_하나를_받는다(tmp_path):
    cfg = make_config(tmp_path)
    rec = MemoryRecorder()
    run(scripted(OK), cfg, CallBudget(), rec)
    assert isinstance(rec.records[0], CallRecord)
