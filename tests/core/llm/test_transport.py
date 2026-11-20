"""진짜 전송층(AnthropicTransport)이 SDK에 넘기는 인자. 네트워크 없이 가짜 클라이언트로 본다."""

from types import SimpleNamespace

from patent_ai.core.llm.transport import AnthropicTransport


class _RecordingMessages:
    """messages.create에 넘어온 인자를 붙잡아 두는 가짜."""

    def __init__(self) -> None:
        self.kwargs: dict | None = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="ok")],
            usage=SimpleNamespace(input_tokens=3, output_tokens=1),
        )


def _transport_with_fake_client() -> tuple[AnthropicTransport, _RecordingMessages]:
    # conftest가 진짜 생성자를 막으므로 __init__을 건너뛰고 가짜 클라이언트를 넣는다
    tr = object.__new__(AnthropicTransport)
    messages = _RecordingMessages()
    tr._client = SimpleNamespace(messages=messages)
    return tr, messages


def test_SDK에_temperature_top_p_top_k를_넘기지_않는다():
    tr, messages = _transport_with_fake_client()
    tr.complete(step="t.s", model="m", prompt="p", effort="medium", max_tokens=5)
    assert messages.kwargs is not None
    assert not {"temperature", "top_p", "top_k"} & messages.kwargs.keys()


def test_SDK에_모델_최대_토큰_프롬프트는_넘긴다():
    tr, messages = _transport_with_fake_client()
    resp = tr.complete(step="t.s", model="m", prompt="p", effort="high", max_tokens=5)
    assert messages.kwargs == {
        "model": "m",
        "max_tokens": 5,
        "output_config": {"effort": "high"},
        "messages": [{"role": "user", "content": "p"}],
    }
    assert resp.text == "ok"
