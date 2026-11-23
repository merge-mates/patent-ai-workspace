"""전송층. 모델 SDK(anthropic·openai)는 이 파일 안에서만 import한다."""

import copy
from dataclasses import dataclass, field
from typing import Protocol

from patent_ai.core.llm.errors import ModelConfigError


@dataclass(frozen=True)
class TransportResponse:
    text: str
    input_tokens: int
    output_tokens: int
    # 모델이 답을 끝낸 이유 (end_turn·max_tokens 등, API 값 그대로). 모르면 None (옛 캐시·기록 파일)
    stop_reason: str | None = None


@dataclass(frozen=True)
class ConverseResponse:
    """tool use 한 차례의 답. content는 API 답 블록(text·tool_use·thinking)을 JSON dict로
    그대로 담는다. 다음 차례 messages에 이 블록을 고치지 않고 돌려줘야 한다."""

    content: list[dict]
    input_tokens: int
    output_tokens: int
    stop_reason: str | None = None


@dataclass(frozen=True)
class TransportUsage:
    """실패한 호출에서 청구됐을 토큰 수 (스트림이 끊기기 전까지 받은 usage).

    output_tokens가 None이면 출력 토큰은 확인되지 않음: SDK는 출력 토큰을 답 끝의
    message_delta에서만 고치므로, 글을 받는 중에 끊기면 message_start 때 값(보통 1)이 남는다.
    """

    input_tokens: int
    output_tokens: int | None


# 서버가 요청을 거절한 오류(429·5xx·4xx 상태): 모델이 돌지 않아 청구가 없다
NOT_BILLED = TransportUsage(0, 0)


class TransportError(Exception):
    """전송 오류(429·연결 오류 등). retryable=True면 다시 불러 볼 만한 오류.

    usage: 이 호출에서 청구됐을 토큰. None이면 확인되지 않음 (스트림 시작 전에 끊겼거나
    요청이 갔는지 모름). NOT_BILLED면 청구가 없음을 안다.
    """

    def __init__(self, message: str, retryable: bool, usage: TransportUsage | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.usage = usage


def is_real_transport(transport) -> bool:
    """돈이 드는 진짜 전송층인가. 허용 목록 방식: is_real=False 표시가 있는 가짜·기록 전송층만
    돈이 안 든다고 보고, 표시가 없는 전송층(래퍼, 새 진짜 전송층)과 None(기본 진짜)은 진짜로 본다.
    과금을 막는 선(상한 필수·기본 파일 캐시)이 모르는 전송층에서 빠지지 않게."""
    return transport is None or getattr(transport, "is_real", True)


class Transport(Protocol):
    def complete(
        self, *, step: str, model: str, prompt: str, effort: str, max_tokens: int
    ) -> TransportResponse: ...

    def converse(
        self,
        *,
        step: str,
        model: str,
        system: str,
        messages: list[dict],
        tools: list[dict],
        effort: str,
        max_tokens: int,
    ) -> ConverseResponse: ...


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
        message = self._stream_message(
            model=model,
            max_tokens=max_tokens,
            output_config={"effort": effort},
            messages=[{"role": "user", "content": prompt}],
        )
        return parse_anthropic_message(message)

    def converse(
        self,
        *,
        step: str,
        model: str,
        system: str,
        messages: list[dict],
        tools: list[dict],
        effort: str,
        max_tokens: int,
    ) -> ConverseResponse:
        # tool use 한 차례. 병렬 도구 호출은 끈다(한 차례에 도구 하나). 도구를 강제로 고르게 하는
        # tool_choice(any/tool)는 쓰지 않는다: 모델이 스스로 도구를 쓸지 끝낼지 정한다.
        message = self._stream_message(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools,
            tool_choice={"type": "auto", "disable_parallel_tool_use": True},
            output_config={"effort": effort},
        )
        return ConverseResponse(
            # 블록을 JSON dict로 바꿔 다음 차례에 그대로 돌려줄 수 있게 한다
            [b.model_dump(mode="json", exclude_none=True) for b in message.content],
            message.usage.input_tokens,
            message.usage.output_tokens,
            message.stop_reason,
        )

    def _stream_message(self, **kwargs):
        import anthropic
        import httpx2  # anthropic SDK가 쓰는 HTTP 라이브러리 (스트림 중 연결 오류가 이 예외로 온다)

        # 스트리밍으로 부른다 (#172): 출력이 길면(max_tokens 64000) 답이 몇 분 걸려 한 번에 받는
        # 호출은 중간에 끊기기 쉽다. 글자를 조금씩 받아 SDK가 모은 최종 Message만 쓰므로
        # 돌려주는 모양(text·토큰 수·stop_reason)은 스트리밍 아닐 때와 같다.
        # effort는 output_config로 넘긴다. temperature는 API에서 빠져 넘기지 않는다 (#134).
        # SDK 예외를 TransportError로 바꿔 던진다. 요청은 with에 들어갈 때 나가고 답은
        # get_final_message에서 받으므로 둘 다 try 안에 둔다.
        # 스트림이 중간에 끊기면 그때까지 받은 usage를 오류에 싣는다 (#194). 입력 토큰은
        # message_start에서 오고, 출력 토큰은 답 끝 message_delta를 받아야 안다 (_partial_usage).
        stream = None  # with에 들어가기 전에 실패하면 None으로 남는다
        try:
            with self._client.messages.stream(**kwargs) as stream:
                return stream.get_final_message()
        except anthropic.APIStatusError as e:
            # 상태 200 = 스트림 중 오류 이벤트 (모델이 돌던 중). 그 밖은 서버가 요청을 거절함
            usage = _partial_usage(stream) if e.status_code == 200 else NOT_BILLED
            raise TransportError(f"{e.status_code} {e.message}", _retryable_status(e), usage) from e
        except anthropic.APIConnectionError as e:
            raise TransportError(f"연결 오류: {e}", True, _partial_usage(stream)) from e
        except httpx2.TransportError as e:
            # 답을 받는 중에 연결이 끊기거나 시간이 넘으면 SDK가 감싸지 않고 그대로 올린다
            raise TransportError(
                f"스트림 중 연결 오류: {type(e).__name__}: {e}", True, _partial_usage(stream)
            ) from e


def _partial_usage(stream) -> TransportUsage | None:
    """끊긴 스트림에서 SDK가 모아 둔 usage를 읽는다. message_start 전이면 None (확인되지 않음)."""
    if stream is None:
        return None
    try:
        # SDK는 message_start를 받기 전이면 assert로 실패한다
        snapshot = stream.current_message_snapshot
    except AssertionError:
        return None
    usage = getattr(snapshot, "usage", None)
    if usage is None:
        return None
    # stop_reason은 message_delta에서야 채워진다. 없으면 출력 토큰은 아직 고쳐지지 않은 값이라
    # 쓰지 않고 확인되지 않음(None)으로 둔다 (적게 잡힌 비용이 확정 값처럼 남지 않게)
    out_tok = usage.output_tokens if snapshot.stop_reason is not None else None
    return TransportUsage(usage.input_tokens or 0, out_tok)


# 스트림 중 오류 이벤트의 종류 가운데 다시 불러 볼 만한 것 (서버 쪽 사정)
_RETRYABLE_ERROR_TYPES = ("overloaded_error", "api_error", "rate_limit_error", "timeout_error")


def _retryable_status(e) -> bool:
    """SDK 상태 오류를 다시 부를 만한가: 429·5xx.

    스트림 중에 온 오류 이벤트는 HTTP 상태가 이미 200이라 상태 코드로는 못 가른다.
    그때는 오류 종류(error.type)가 서버 쪽 사정(과부하 등)일 때만 다시 부른다.
    """
    if e.status_code == 429 or e.status_code >= 500:
        return True
    return e.status_code == 200 and e.type in _RETRYABLE_ERROR_TYPES


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

    def converse(
        self,
        *,
        step: str,
        model: str,
        system: str,
        messages: list[dict],
        tools: list[dict],
        effort: str,
        max_tokens: int,
    ) -> ConverseResponse:
        # messages는 사본을 쌓는다 (부른 쪽이 나중에 목록을 늘려도 그때 받은 모양이 남게)
        self.calls.append(
            dict(
                step=step,
                model=model,
                system=system,
                messages=copy.deepcopy(messages),
                tools=copy.deepcopy(tools),
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
