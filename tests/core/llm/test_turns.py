"""task-1: tool use 한 차례 호출 길 (call_model_turn). 가짜 전송층만, 네트워크·API 키 없음."""

from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from patent_ai.core.llm.cache import MemoryCache, make_turn_cache_key
from patent_ai.core.llm.errors import (
    ModelCallFailed,
    ModelCallLimitExceeded,
    ModelConfigError,
    ModelOutputInvalid,
)
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import (
    NOT_BILLED,
    AnthropicTransport,
    ConverseResponse,
    FakeTransport,
    TransportError,
)
from patent_ai.core.llm.turns import call_model_turn

FIX = Path(__file__).parent.parent.parent / "fixtures" / "llm"
SYS_VARS = {"lines": 2, "text": "청구항 1은 진보성이 없다"}
TOOLS = [{"name": "search", "description": "검색", "input_schema": {"type": "object"}}]
TOOL_USE = {"type": "tool_use", "id": "tu_1", "name": "search", "input": {"q": "도 3"}}
THINKING = {"type": "thinking", "thinking": "생각", "signature": "sig"}
FIRST = ConverseResponse([THINKING, TOOL_USE], 500, 80, "tool_use")
SECOND = ConverseResponse([{"type": "text", "text": "끝"}], 700, 20, "end_turn")
USER = {"role": "user", "content": "시작"}


def make_config(tmp_path, **limits):
    extra = "".join(f"  {k}: {v}\n" for k, v in limits.items())
    (tmp_path / "t.yaml").write_text(
        "s:\n  model: fake-model-1\n  effort: medium\n  max_tokens: 256\n"
        "  prompt: prompts/summarize.txt\n"
        "  price_per_mtok_input: 3.0\n  price_per_mtok_output: 15.0\n" + extra,
        encoding="utf-8",
    )
    return tmp_path


def fake(*items):
    return FakeTransport({"t.s": list(items)})


def turn(ctx, cfg, messages, tools=TOOLS, sleeps=None, variables=SYS_VARS):
    return call_model_turn(
        "t.s",
        variables,
        messages,
        tools,
        ctx=ctx,
        config_dir=cfg,
        root=FIX,
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
    )


def make_ctx(transport, cache=None, budget=None):
    return RunContext("run-1", budget or CallBudget(), MemoryRecorder(), transport, cache)


def test_평소_두_차례_두번째_messages에_첫_답_블록이_그대로_있다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=5)
    t = fake(FIRST, SECOND)
    ctx = make_ctx(t)
    r1 = turn(ctx, cfg, [USER])
    assert r1.content == [THINKING, TOOL_USE]
    assert r1.stop_reason == "tool_use" and r1.from_cache is False
    assert r1.model == "fake-model-1" and (r1.input_tokens, r1.output_tokens) == (500, 80)
    # 500*3/1e6 + 80*15/1e6
    assert r1.cost == pytest.approx(0.0027)
    result = {"type": "tool_result", "tool_use_id": "tu_1", "content": "x"}
    messages = [
        USER,
        {"role": "assistant", "content": r1.content},
        {"role": "user", "content": [result]},
    ]
    r2 = turn(ctx, cfg, messages)
    assert r2.content == [{"type": "text", "text": "끝"}]
    second_call = t.calls[1]
    assert second_call["messages"][1] == {"role": "assistant", "content": [THINKING, TOOL_USE]}
    assert (
        second_call["system"]
        == "다음 거절이유를 2 줄로 요약하세요.\n본문: 청구항 1은 진보성이 없다\n"
    )
    assert second_call["tools"] == TOOLS
    assert [r.outcome for r in ctx.recorder.records] == ["ok", "ok"]


def test_같은_messages_두번째는_캐시_적중이고_전송_0회_상한에_안_센다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=1)
    t = fake(FIRST)
    ctx = make_ctx(t, cache=MemoryCache())
    turn(ctx, cfg, [USER])
    r = turn(ctx, cfg, [USER])
    assert r.from_cache is True and r.cost == 0.0
    assert r.content == [THINKING, TOOL_USE] and r.stop_reason == "tool_use"
    assert len(t.calls) == 1
    assert [x.outcome for x in ctx.recorder.records] == ["ok", "cache_hit"]
    assert ctx.recorder.records[1].transport_try == 0


def _key(**over):
    base = dict(
        step="s",
        model="m",
        prompt_template="p",
        system_variables={"a": 1},
        messages=[USER],
        tools=TOOLS,
        effort="medium",
        max_tokens=10,
    )
    return make_turn_cache_key(**{**base, **over})


def test_캐시_키는_입력이_하나라도_바뀌면_달라진다():
    base = _key()
    assert base == _key()
    assert len(base) == 64
    assert _key(messages=[{"role": "user", "content": "시작."}]) != base
    assert _key(tools=[{**TOOLS[0], "description": "다름"}]) != base
    assert _key(system_variables={"a": 2}) != base
    assert _key(prompt_template="q") != base
    assert _key(step="s2") != base
    assert _key(model="m2") != base
    assert _key(effort="high") != base
    assert _key(max_tokens=11) != base


def test_messages_한_글자_다르면_캐시를_못_쓴다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=5)
    t = fake(FIRST, SECOND)
    ctx = make_ctx(t, cache=MemoryCache())
    turn(ctx, cfg, [USER])
    r = turn(ctx, cfg, [{"role": "user", "content": "시작!"}])
    assert r.from_cache is False and len(t.calls) == 2


def test_tools가_다르면_캐시를_못_쓴다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=5)
    t = fake(FIRST, SECOND)
    ctx = make_ctx(t, cache=MemoryCache())
    turn(ctx, cfg, [USER])
    turn(ctx, cfg, [USER], tools=[{**TOOLS[0], "name": "other"}])
    assert len(t.calls) == 2


def test_상한_1이면_두번째_차례에서_멈추고_limit_exceeded가_남는다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=1)
    t = fake(FIRST, SECOND)
    ctx = make_ctx(t)
    turn(ctx, cfg, [USER])
    with pytest.raises(ModelCallLimitExceeded):
        turn(ctx, cfg, [USER, {"role": "assistant", "content": FIRST.content}])
    assert len(t.calls) == 1
    assert [r.outcome for r in ctx.recorder.records] == ["ok", "limit_exceeded"]


def test_429_한_번_뒤_성공하면_재시도하고_기록이_두_줄(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=5, max_retries=2)
    t = fake(TransportError("429", True, NOT_BILLED), FIRST)
    ctx = make_ctx(t)
    sleeps: list[float] = []
    r = turn(ctx, cfg, [USER], sleeps=sleeps)
    assert r.content == [THINKING, TOOL_USE]
    assert sleeps == [1.0]
    recs = ctx.recorder.records
    assert [(x.outcome, x.transport_try) for x in recs] == [("transport_error", 1), ("ok", 2)]
    assert recs[0].input_tokens == 0


def test_재시도_못하는_오류는_ModelCallFailed(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=5, max_retries=2)
    ctx = make_ctx(fake(TransportError("400", False, NOT_BILLED)))
    with pytest.raises(ModelCallFailed):
        turn(ctx, cfg, [USER])
    assert [r.outcome for r in ctx.recorder.records] == ["transport_error"]


def test_받은_usage를_모르는_전송_오류는_기록이_확인되지_않음_None(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=5)
    ctx = make_ctx(fake(TransportError("연결", False, None)))
    with pytest.raises(ModelCallFailed):
        turn(ctx, cfg, [USER])
    rec = ctx.recorder.records[0]
    assert rec.input_tokens is None and rec.cost is None


def test_잘림_max_tokens면_ModelOutputInvalid_캐시에_안_쓴다(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=5)
    cut = ConverseResponse([{"type": "tool_use", "id": "x", "name": "s"}], 10, 256, "max_tokens")
    cache = MemoryCache()
    ctx = make_ctx(fake(cut), cache=cache)
    with pytest.raises(ModelOutputInvalid) as ei:
        turn(ctx, cfg, [USER])
    assert ei.value.truncated and ei.value.invalid_kind == "truncated"
    assert cache._data == {}
    rec = ctx.recorder.records[0]
    assert rec.outcome == "output_truncated" and rec.stop_reason == "max_tokens"


class _RealLike:
    """진짜 전송층 흉내 (is_real=False 표시가 없다)."""

    def __init__(self) -> None:
        self.n = 0

    def converse(self, **kw):
        self.n += 1
        return FIRST


def test_진짜_전송층인데_상한이_없으면_부르기_전에_멈춘다(tmp_path):
    cfg = make_config(tmp_path)
    inner = _RealLike()
    ctx = make_ctx(inner, cache=MemoryCache())
    with pytest.raises(ModelConfigError, match="max_model_calls"):
        turn(ctx, cfg, [USER])
    assert inner.n == 0


def test_ctx가_없으면_설정_오류(tmp_path):
    cfg = make_config(tmp_path, max_model_calls=5)
    with pytest.raises(ModelConfigError):
        call_model_turn("t.s", SYS_VARS, [USER], TOOLS, ctx=None, config_dir=cfg, root=FIX)


def test_FakeTransport는_없는_step이거나_답을_다_쓰면_ModelConfigError():
    f = FakeTransport({"a": [FIRST]})
    kw = dict(model="m", system="s", messages=[USER], tools=TOOLS, effort="low", max_tokens=5)
    f.converse(step="a", **kw)
    with pytest.raises(ModelConfigError):
        f.converse(step="a", **kw)
    with pytest.raises(ModelConfigError):
        f.converse(step="b", **kw)


def test_FakeTransport는_messages_사본을_쌓는다():
    f = FakeTransport({"a": [FIRST]})
    msgs = [dict(USER)]
    f.converse(
        step="a", model="m", system="s", messages=msgs, tools=TOOLS, effort="low", max_tokens=5
    )
    msgs.append({"role": "assistant", "content": "x"})
    assert len(f.calls[0]["messages"]) == 1


# ---- AnthropicTransport.converse (SDK는 가짜 클라이언트) ----
_REQ = httpx2.Request("POST", "https://example.invalid/v1/messages")


class _Block:
    def __init__(self, d):
        self.d = d

    def model_dump(self, mode, exclude_none):
        assert mode == "json" and exclude_none is True
        return self.d


class _Stream:
    def __init__(self, message=None, on_read=None, snapshot=None):
        self.message, self.on_read, self.snapshot = message, on_read, snapshot
        self.kwargs = None

    def stream(self, **kwargs):
        self.kwargs = kwargs
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return None

    @property
    def current_message_snapshot(self):
        assert self.snapshot is not None
        return self.snapshot

    def get_final_message(self):
        if self.on_read is not None:
            raise self.on_read
        return self.message


def _anthropic(stream) -> AnthropicTransport:
    tr = object.__new__(AnthropicTransport)
    tr._client = SimpleNamespace(messages=stream)
    return tr


CONV = dict(
    step="s", model="m", system="sys", messages=[USER], tools=TOOLS, effort="high", max_tokens=9
)


def test_converse는_스트리밍으로_부르고_블록을_JSON_dict로_돌려준다():
    msg = SimpleNamespace(
        content=[_Block(THINKING), _Block(TOOL_USE)],
        usage=SimpleNamespace(input_tokens=3, output_tokens=4),
        stop_reason="tool_use",
    )
    s = _Stream(msg)
    resp = _anthropic(s).converse(**CONV)
    assert resp == ConverseResponse([THINKING, TOOL_USE], 3, 4, "tool_use")
    assert s.kwargs == {
        "model": "m",
        "max_tokens": 9,
        "system": "sys",
        "messages": [USER],
        "tools": TOOLS,
        "tool_choice": {"type": "auto", "disable_parallel_tool_use": True},
        "output_config": {"effort": "high"},
    }


def test_converse_429는_다시_부를_만한_TransportError_청구_없음():
    err = anthropic.APIStatusError("x", response=httpx2.Response(429, request=_REQ), body=None)
    with pytest.raises(TransportError) as ei:
        _anthropic(_Stream(on_read=err)).converse(**CONV)
    assert ei.value.retryable is True and ei.value.usage == NOT_BILLED


def test_converse_400은_다시_부르지_않는다():
    err = anthropic.APIStatusError("x", response=httpx2.Response(400, request=_REQ), body=None)
    with pytest.raises(TransportError) as ei:
        _anthropic(_Stream(on_read=err)).converse(**CONV)
    assert ei.value.retryable is False


def test_converse_스트림_연결_끊김은_받은_입력_토큰만_싣는다():
    usage = SimpleNamespace(input_tokens=42, output_tokens=1)
    snap = SimpleNamespace(usage=usage, stop_reason=None)
    with pytest.raises(TransportError) as ei:
        _anthropic(_Stream(on_read=httpx2.ReadError("끊김"), snapshot=snap)).converse(**CONV)
    assert ei.value.retryable is True
    assert (ei.value.usage.input_tokens, ei.value.usage.output_tokens) == (42, None)
