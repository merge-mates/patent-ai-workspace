"""전송층. 모델 SDK(anthropic)는 이 파일 안에서만 import한다."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class TransportResponse:
    text: str
    input_tokens: int
    output_tokens: int


class Transport(Protocol):
    def complete(
        self, *, step: str, model: str, prompt: str, temperature: float, max_tokens: int
    ) -> TransportResponse: ...


def parse_anthropic_message(message) -> TransportResponse:
    """SDK 응답에서 text 블록을 이어 붙이고 토큰 수를 읽는다."""
    text = "".join(b.text for b in message.content if b.type == "text")
    return TransportResponse(text, message.usage.input_tokens, message.usage.output_tokens)


class AnthropicTransport:
    """진짜 전송층. 키는 SDK가 환경 변수에서 읽는다 (코드에서 다루지 않음)."""

    def __init__(self) -> None:
        import anthropic  # 여기서만 import

        self._client = anthropic.Anthropic()

    def complete(
        self, *, step: str, model: str, prompt: str, temperature: float, max_tokens: int
    ) -> TransportResponse:
        message = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        return parse_anthropic_message(message)


@dataclass
class FakeTransport:
    """테스트용. step 이름으로 미리 쓴 답을 돌려주고, 받은 호출을 calls에 쌓는다."""

    responses: dict[str, TransportResponse]
    calls: list[dict] = field(default_factory=list)

    def complete(
        self, *, step: str, model: str, prompt: str, temperature: float, max_tokens: int
    ) -> TransportResponse:
        self.calls.append(
            dict(
                step=step,
                model=model,
                prompt=prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        )
        return self.responses[step]
