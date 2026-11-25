"""임베딩 전송층 규약, Gemini REST, 가짜·기록 전송층."""

import hashlib
import json
import math
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import httpx

from patent_ai.core.llm.errors import ModelConfigError, RecordingMissing
from patent_ai.core.llm.transport import (  # noqa: F401 (밖에서 여기로 가져다 씀)
    EmbedResponse,
    OpenAIEmbedTransport,
    TransportError,
    parse_openai_embeddings,
)


class EmbedTransport(Protocol):
    def embed(self, *, step: str, model: str, texts: list[str]) -> EmbedResponse: ...


class GeminiEmbedTransport:
    """Gemini Embedding 001의 검색 작업 유형과 출력 차원을 지정한다."""

    # 2,048 토큰 한도에 모델 프레이밍 여유를 두고 조용한 잘림을 막는다.
    _MAX_TEXT_TOKENS = 2000

    def __init__(self, *, task_type: str, dimensions: int) -> None:
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ModelConfigError("Gemini 임베딩에 GEMINI_API_KEY가 필요함")
        self._api_key = api_key
        self._task_type = task_type
        self._dimensions = dimensions

    def embed(self, *, step: str, model: str, texts: list[str]) -> EmbedResponse:
        resource = f"models/{model}"
        contents = [{"parts": [{"text": text}]} for text in texts]
        with httpx.Client(
            base_url="https://generativelanguage.googleapis.com/v1beta/",
            headers={"x-goog-api-key": self._api_key},
            timeout=30.0,
        ) as client:
            counts = [
                self._post(client, f"{resource}:countTokens", {"contents": [content]})[
                    "totalTokens"
                ]
                for content in contents
            ]
            if any(count > self._MAX_TEXT_TOKENS for count in counts):
                raise TransportError(
                    f"{step}: Gemini 임베딩 입력이 {self._MAX_TEXT_TOKENS}토큰을 넘음", False
                )
            requests = [
                {
                    "model": resource,
                    "content": content,
                    "taskType": self._task_type,
                    "outputDimensionality": self._dimensions,
                }
                for content in contents
            ]
            response = self._post(client, f"{resource}:batchEmbedContents", {"requests": requests})

        vectors = []
        for item in response["embeddings"]:
            vector = item["values"]
            norm = math.sqrt(math.fsum(value * value for value in vector))
            if len(vector) != self._dimensions or not math.isfinite(norm) or norm <= 0:
                raise TransportError(f"{step}: Gemini 임베딩 벡터의 차원 또는 길이가 잘못됨", False)
            vectors.append([value / norm for value in vector])
        return EmbedResponse(vectors, sum(counts))

    @staticmethod
    def _post(client: httpx.Client, path: str, payload: dict) -> dict:
        try:
            response = client.post(path, json=payload)
        except httpx.TransportError as error:
            raise TransportError(f"Gemini 연결 오류 ({type(error).__name__})", True) from None
        if not response.is_success:
            status = response.status_code
            raise TransportError(f"Gemini HTTP {status}", status == 429 or status >= 500)
        return response.json()


@dataclass
class FakeEmbedTransport:
    """테스트용. 글 → 벡터 함수로 답하고, 받은 호출을 calls에 쌓는다.

    errors에 예외를 두면 앞 호출부터 차례로 그 예외를 낸다 (재시도 시험용).
    """

    vector_of: Callable[[str], list[float]]
    errors: list[Exception] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    is_real = False  # 돈 안 드는 전송층 (is_real_transport)

    def embed(self, *, step: str, model: str, texts: list[str]) -> EmbedResponse:
        self.calls.append(dict(step=step, model=model, texts=list(texts)))
        if self.errors:
            raise self.errors.pop(0)
        # 지어낸 토큰 수: 글자 수 합
        return EmbedResponse([self.vector_of(t) for t in texts], sum(len(t) for t in texts))


def embed_recording_key(*, step: str, model: str, text: str) -> str:
    """기록 파일 이름: (단계, 모델, 글)의 sha256. 글자 하나만 달라도 다른 키."""
    raw = json.dumps(dict(step=step, model=model, text=text), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def save_embed_recording(
    directory: Path, vector: list[float], *, step: str, model: str, text: str
) -> Path:
    """기록된 벡터 하나를 저장한다. 이미 있으면 멈춘다 (덮어쓰지 않음)."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{embed_recording_key(step=step, model=model, text=text)}.json"
    if path.exists():
        raise FileExistsError(f"이미 기록이 있음: {path}")
    data = {"vector": vector, "model": model, "step": step}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


class RecordedEmbedTransport:
    """저장한 벡터만 돌려준다. 하나라도 없으면 RecordingMissing (진짜 호출로 안 넘어감)."""

    is_real = False  # 돈 안 드는 전송층 (is_real_transport)

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def embed(self, *, step: str, model: str, texts: list[str]) -> EmbedResponse:
        vectors = []
        for text in texts:
            path = self.directory / f"{embed_recording_key(step=step, model=model, text=text)}.json"
            if not path.is_file():
                # 글 원문은 메시지에 넣지 않는다 (파일 이름만)
                raise RecordingMissing(f"기록된 벡터가 없음: {path.name} (step={step})")
            d = json.loads(path.read_text(encoding="utf-8"))
            if d.get("model") != model:
                raise ModelConfigError(f"기록의 모델 {d.get('model')!r}이 설정 {model!r}과 다름")
            vectors.append(d["vector"])
        return EmbedResponse(vectors, 0)
