"""전송층. 모델 SDK(anthropic·openai)는 이 파일 안에서만 import한다."""

from dataclasses import dataclass, field
from typing import Protocol

from patent_ai.core.llm.errors import ModelConfigError


@dataclass(frozen=True)
class TransportResponse:
    text: str
    input_tokens: int
    output_tokens: int
    # 모델이 답을 끝낸 이유 (end_turn·max_tokens 등, API 값 그대로). 모르면 None (옛 캐시·녹화)
    stop_reason: str | None = None


class TransportError(Exception):
    """전송 오류(429·연결 오류 등). retryable=True면 다시 불러 볼 만한 오류."""

    def __init__(self, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


def is_real_transport(transport) -> bool:
    """돈이 드는 진짜 전송층인가. 허용 목록 방식: is_real=False 표시가 있는 가짜·기록 전송층만
    돈이 안 든다고 보고, 표시가 없는 전송층(래퍼, 새 진짜 전송층)과 None(기본 진짜)은 진짜로 본다.
    과금을 막는 선(상한 필수·기본 파일 캐시)이 모르는 전송층에서 빠지지 않게."""
    return transport is None or getattr(transport, "is_real", True)


class Transport(Protocol):
    def complete(
        self, *, step: str, model: str, prompt: str, effort: str, max_tokens: int
    ) -> TransportResponse: ...


def parse_anthropic_message(message) -> TransportResponse:
    """SDK 응답에서 text 블록을 이어 붙이고 토큰 수와 답을 끝낸 이유(stop_reason)를 읽는다."""
    text = "".join(b.text for b in message.content if b.type == "text")
    return TransportResponse(
        text, message.usage.input_tokens, message.usage.output_tokens, message.stop_reason
    )


class AnthropicTransport:
    """진짜 전송층. 키는 SDK가 환경 변수에서 읽는다 (코드에서 다루지 않음)."""

    def __init__(self) -> None:
        import anthropic  # 여기서만 import

        self._client = anthropic.Anthropic()

    def complete(
        self, *, step: str, model: str, prompt: str, effort: str, max_tokens: int
    ) -> TransportResponse:
        import anthropic

        # effort는 output_config로 넘긴다. temperature는 API에서 빠져 넘기지 않는다 (#134).
        # SDK 예외를 TransportError로 바꿔 던진다 (429·5xx·연결 오류만 다시 부를 만함)
        try:
            message = self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                output_config={"effort": effort},
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIStatusError as e:
            retryable = e.status_code == 429 or e.status_code >= 500
            raise TransportError(f"{e.status_code} {e.message}", retryable) from e
        except anthropic.APIConnectionError as e:
            raise TransportError(f"연결 오류: {e}", True) from e
        return parse_anthropic_message(message)


@dataclass
class FakeTransport:
    """테스트용. step 이름으로 미리 쓴 답을 돌려주고, 받은 호출을 calls에 쌓는다.

    값이 목록이면 시도마다 차례로 (답 또는 예외), 목록이 아니면 늘 같은 것을 낸다.
    없는 step이거나 목록을 다 썼으면 ModelConfigError (테스트 준비가 모자란 것).
    """

    responses: dict[str, object]
    calls: list[dict] = field(default_factory=list)
    is_real = False  # 돈 안 드는 전송층 (is_real_transport)
    _used: dict[str, int] = field(default_factory=dict)

    def complete(
        self, *, step: str, model: str, prompt: str, effort: str, max_tokens: int
    ) -> TransportResponse:
        self.calls.append(
            dict(
                step=step,
                model=model,
                prompt=prompt,
                effort=effort,
                max_tokens=max_tokens,
            )
        )
        if step not in self.responses:
            raise ModelConfigError(f"FakeTransport에 {step!r}의 답이 없음")
        item = self.responses[step]
        if isinstance(item, list):
            i = self._used.get(step, 0)
            if i >= len(item):
                raise ModelConfigError(f"FakeTransport의 {step!r} 답 목록을 다 씀 ({len(item)}개)")
            self._used[step] = i + 1
            item = item[i]
        if isinstance(item, Exception):
            raise item
        return item


# ---- 임베딩 (#66) ----
@dataclass(frozen=True)
class EmbedResponse:
    vectors: list[list[float]]  # 받은 글 순서 그대로
    input_tokens: int


def parse_openai_embeddings(resp) -> EmbedResponse:
    """SDK 응답의 data를 index 순서로 줄 세워 벡터를 읽는다."""
    rows = sorted(resp.data, key=lambda d: d.index)
    return EmbedResponse([list(d.embedding) for d in rows], resp.usage.prompt_tokens)


def make_openai_client():
    """OpenAI SDK 클라이언트. 키가 없으면 traceback 대신 설정 오류 한 줄 (키 값은 안 다룸)."""
    import openai  # 여기서만 import

    try:
        return openai.OpenAI()
    except openai.OpenAIError as e:
        raise ModelConfigError(
            "OPENAI_API_KEY가 없음: .env에 넣고 `uv run --env-file <.env 경로> ...`로 실행"
        ) from e


class OpenAIEmbedTransport:
    """진짜 임베딩 전송층. 키는 SDK가 환경 변수(OPENAI_API_KEY)에서 읽는다."""

    def __init__(self) -> None:
        self._client = make_openai_client()

    def embed(self, *, step: str, model: str, texts: list[str]) -> EmbedResponse:
        import openai

        # SDK 예외를 TransportError로 바꿔 던진다 (429·5xx·연결 오류만 다시 부를 만함)
        try:
            resp = self._client.embeddings.create(model=model, input=texts)
        except openai.APIStatusError as e:
            retryable = e.status_code == 429 or e.status_code >= 500
            raise TransportError(f"{e.status_code} {e.message}", retryable) from e
        except openai.APIConnectionError as e:
            raise TransportError(f"연결 오류: {e}", True) from e
        return parse_openai_embeddings(resp)
