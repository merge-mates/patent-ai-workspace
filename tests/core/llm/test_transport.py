"""진짜 전송층(AnthropicTransport)이 SDK 스트리밍을 쓰는 법. 네트워크 없이 가짜 클라이언트로 본다.

진짜 SDK(anthropic 2.10)의 모양을 따라 만든 가짜: `messages.stream(**kwargs)`는 컨텍스트 매니저를
돌려주고, 요청은 `with`에 들어갈 때 나가며, `stream.get_final_message()`가 다 받은 Message를 준다.
"""

from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from patent_ai.core.llm.transport import (
    AnthropicTransport,
    TransportError,
    TransportResponse,
    TransportUsage,
)

_REQ = httpx2.Request("POST", "https://example.invalid/v1/messages")
KW = dict(step="t.s", model="m", prompt="p", effort="medium", max_tokens=5)


def _message(text="ok", stop_reason="end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=3, output_tokens=1),
        stop_reason=stop_reason,
    )


class _FakeStreamingMessages:
    """messages.stream만 있는 가짜 (create가 없어 스트리밍 아닌 호출은 AttributeError).

    on_enter: with에 들어갈 때(요청을 보낼 때) 던질 예외.
    on_read: get_final_message에서(답을 받는 중에) 던질 예외.
    snapshot: 끊기기 전까지 SDK가 모아 둔 Message (message_start를 받았으면 있음, 아니면 None).
    """

    def __init__(self, message=None, on_enter=None, on_read=None, snapshot=None) -> None:
        self.message = message or _message()
        self.on_enter, self.on_read = on_enter, on_read
        self.snapshot = snapshot
        self.kwargs: dict | None = None
        self.closed = False

    def stream(self, **kwargs):
        self.kwargs = kwargs
        return self

    def __enter__(self):
        if self.on_enter is not None:
            raise self.on_enter
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.closed = True  # 예외를 삼키지 않는다 (None)

    @property
    def current_message_snapshot(self):
        # 진짜 SDK처럼 message_start 전이면 assert로 실패한다
        assert self.snapshot is not None
        return self.snapshot

    def get_final_message(self):
        if self.on_read is not None:
            raise self.on_read
        return self.message


def _transport(messages: _FakeStreamingMessages) -> AnthropicTransport:
    # conftest가 진짜 생성자를 막으므로 __init__을 건너뛰고 가짜 클라이언트를 넣는다
    tr = object.__new__(AnthropicTransport)
    tr._client = SimpleNamespace(messages=messages)
    return tr


def test_SDK에_temperature_top_p_top_k를_넘기지_않는다():
    messages = _FakeStreamingMessages()
    _transport(messages).complete(**KW)
    assert messages.kwargs is not None
    assert not {"temperature", "top_p", "top_k"} & messages.kwargs.keys()


def test_스트리밍으로_부르고_모델_최대_토큰_프롬프트_effort를_넘긴다():
    messages = _FakeStreamingMessages()
    resp = _transport(messages).complete(**{**KW, "effort": "high"})
    assert messages.kwargs == {
        "model": "m",
        "max_tokens": 5,
        "output_config": {"effort": "high"},
        "messages": [{"role": "user", "content": "p"}],
    }
    assert resp == TransportResponse("ok", 3, 1, "end_turn")
    assert messages.closed  # with를 빠져나와 연결을 닫았다


def test_잘린_답이면_stop_reason이_max_tokens():
    messages = _FakeStreamingMessages(_message('{"title": "진보', "max_tokens"))
    resp = _transport(messages).complete(**KW)
    assert (resp.text, resp.stop_reason) == ('{"title": "진보', "max_tokens")


def _status_error(code, error_type=None):
    body = {"type": "error", "error": {"type": error_type, "message": "x"}} if error_type else None
    resp = httpx2.Response(code, request=_REQ)
    return anthropic.APIStatusError(f"에러 {code}", response=resp, body=body)


# 요청을 보낼 때 나는 오류와 답을 받는 중에 나는 오류 둘 다 TransportError로 바꾼다
@pytest.mark.parametrize("where", ["on_enter", "on_read"])
@pytest.mark.parametrize(
    "make_exc,retryable",
    [
        (lambda: _status_error(429), True),
        (lambda: _status_error(500), True),
        (lambda: _status_error(529), True),
        (lambda: _status_error(401), False),
        (lambda: _status_error(400), False),
        (lambda: anthropic.APIConnectionError(request=_REQ), True),
        (lambda: anthropic.APITimeoutError(request=_REQ), True),
    ],
)
def test_SDK_예외를_TransportError로_바꾸고_다시_부를지_정한다(where, make_exc, retryable):
    messages = _FakeStreamingMessages(**{where: make_exc()})
    with pytest.raises(TransportError) as e:
        _transport(messages).complete(**KW)
    assert e.value.retryable is retryable
    assert messages.closed is (where == "on_read")  # 열린 스트림은 오류가 나도 닫는다


# 스트림 중 오류 이벤트는 HTTP 상태가 이미 200이라 오류 종류(error.type)로 다시 부를지 정한다
@pytest.mark.parametrize(
    "error_type,retryable",
    [
        ("overloaded_error", True),
        ("api_error", True),
        ("rate_limit_error", True),
        ("timeout_error", True),
        ("invalid_request_error", False),
        (None, False),
    ],
)
def test_스트림_중_오류_이벤트는_오류_종류로_다시_부를지_정한다(error_type, retryable):
    messages = _FakeStreamingMessages(on_read=_status_error(200, error_type))
    with pytest.raises(TransportError) as e:
        _transport(messages).complete(**KW)
    assert e.value.retryable is retryable


def test_답을_받는_중_연결이_끊기면_다시_부를_만한_TransportError():
    # 스트림을 읽는 중의 연결 오류는 SDK가 감싸지 않고 httpx2 예외 그대로 올라온다
    messages = _FakeStreamingMessages(on_read=httpx2.ReadError("끊김"))
    with pytest.raises(TransportError) as e:
        _transport(messages).complete(**KW)
    assert e.value.retryable is True
    assert messages.closed


# ---- #194 스트림이 끊길 때 받은 usage ----
def _snapshot(input_tokens=1200, output_tokens=37):
    return SimpleNamespace(
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    )


def test_답을_받는_중_끊기면_그때까지_받은_usage를_오류에_싣는다():
    messages = _FakeStreamingMessages(on_read=httpx2.ReadError("끊김"), snapshot=_snapshot())
    with pytest.raises(TransportError) as e:
        _transport(messages).complete(**KW)
    assert e.value.usage == TransportUsage(1200, 37)


def test_스트림_중_오류_이벤트도_받은_usage를_싣는다():
    messages = _FakeStreamingMessages(
        on_read=_status_error(200, "overloaded_error"), snapshot=_snapshot(800, 5)
    )
    with pytest.raises(TransportError) as e:
        _transport(messages).complete(**KW)
    assert e.value.usage == TransportUsage(800, 5)


def test_message_start_전에_끊기면_usage는_확인되지_않음():
    messages = _FakeStreamingMessages(on_read=httpx2.ReadError("끊김"))
    with pytest.raises(TransportError) as e:
        _transport(messages).complete(**KW)
    assert e.value.usage is None


def test_요청을_보낼_때_연결_오류면_usage는_확인되지_않음():
    messages = _FakeStreamingMessages(on_enter=anthropic.APIConnectionError(request=_REQ))
    with pytest.raises(TransportError) as e:
        _transport(messages).complete(**KW)
    assert e.value.usage is None


@pytest.mark.parametrize("code", [429, 500, 400])
def test_서버가_요청을_거절한_상태_오류는_청구_없음(code):
    messages = _FakeStreamingMessages(on_enter=_status_error(code))
    with pytest.raises(TransportError) as e:
        _transport(messages).complete(**KW)
    assert e.value.usage == TransportUsage(0, 0)


def test_TransportError의_usage는_안_주면_None():
    assert TransportError("x", True).usage is None
