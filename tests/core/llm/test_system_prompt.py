"""P0.5: 단계 설정의 system_prompt 파일을 전송층의 system 칸으로 보낸다 (의견서·저지용).

system_prompt가 없는 단계는 지금 그대로(전송층에 system 인자를 안 넘기고, 캐시·기록 키도 그대로).
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from patent_ai.core.llm.cache import MemoryCache, make_cache_key
from patent_ai.core.llm.client import call_model
from patent_ai.core.llm.config import load_step_config
from patent_ai.core.llm.errors import ModelConfigError
from patent_ai.core.llm.limits import CallBudget
from patent_ai.core.llm.recorded import recording_key
from patent_ai.core.llm.transport import AnthropicTransport, FakeTransport, TransportResponse

FIX = Path(__file__).parent.parent.parent / "fixtures" / "llm"
VARS = {"lines": 2, "text": "청구항 1은 진보성이 없다"}


def run(transport, step, cache=None):
    return call_model(
        step,
        VARS,
        None,
        "run-1",
        transport=transport,
        cache=cache,
        config_dir=FIX / "config",
        root=FIX,
        budget=CallBudget(),
    )


def test_설정의_system_prompt를_읽는다():
    assert load_step_config("test.withsystem", FIX / "config").system_prompt == (
        "prompts/summarize.system.txt"
    )
    assert load_step_config("test.summarize", FIX / "config").system_prompt is None


def test_system_prompt가_있으면_파일_글자가_system으로_간다():
    fake = FakeTransport({"test.withsystem": TransportResponse("x", 1, 1)})
    run(fake, "test.withsystem")
    assert fake.calls[0]["system"] == "너는 거절이유를 짧게 요약하는 도우미다.\n"
    # user 쪽 프롬프트는 그대로 채워진다
    assert fake.calls[0]["prompt"].startswith("다음 거절이유를 2 줄로")


def test_system_prompt가_없으면_전송층에_system을_넘기지_않는다():
    fake = FakeTransport({"test.summarize": TransportResponse("x", 1, 1)})
    run(fake, "test.summarize")
    assert "system" not in fake.calls[0]


def test_system_prompt에_변수가_있으면_설정_오류():
    fake = FakeTransport({"test.badsystem": TransportResponse("x", 1, 1)})
    with pytest.raises(ModelConfigError):
        run(fake, "test.badsystem")
    assert fake.calls == []


def test_system_글자가_바뀌면_캐시_키가_바뀌고_없으면_예전_키_그대로():
    base = dict(
        step="s", model="m", prompt_template="p", variables={}, effort="e", max_tokens=1, attempt=1
    )
    old = make_cache_key(**base)
    assert make_cache_key(**base, system_template=None) == old
    a = make_cache_key(**base, system_template="A")
    assert a != old and a != make_cache_key(**base, system_template="B")


def test_system이_있는_호출은_캐시에서_따로_적중한다():
    cache = MemoryCache()
    fake = FakeTransport(
        {
            "test.withsystem": TransportResponse("with", 1, 1),
            "test.summarize": TransportResponse("without", 1, 1),
        }
    )
    assert run(fake, "test.withsystem", cache).text == "with"
    again = run(fake, "test.withsystem", cache)
    assert again.from_cache and again.text == "with"


def test_기록_키는_system이_없으면_예전과_같고_있으면_다르다():
    kw = dict(step="s", model="m", prompt="p", effort="e", max_tokens=1)
    assert recording_key(**kw, system=None) == recording_key(**kw)
    assert recording_key(**kw, system="S") != recording_key(**kw)


class _Stream:
    def __init__(self, messages):
        self.messages = messages

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="ok")],
            usage=SimpleNamespace(input_tokens=3, output_tokens=1),
            stop_reason="end_turn",
        )


class _Messages:
    kwargs = None

    def stream(self, **kwargs):
        self.kwargs = kwargs
        return _Stream(self)


def _transport(messages):
    tr = object.__new__(AnthropicTransport)
    tr._client = SimpleNamespace(messages=messages)
    return tr


def test_Anthropic_전송층은_system이_있을_때만_system_인자를_보낸다():
    kw = dict(step="s", model="m", prompt="p", effort="high", max_tokens=5)
    m = _Messages()
    _transport(m).complete(**kw, system="시스템")
    assert m.kwargs["system"] == "시스템"
    assert m.kwargs["messages"] == [{"role": "user", "content": "p"}]
    m2 = _Messages()
    _transport(m2).complete(**kw)
    assert "system" not in m2.kwargs
