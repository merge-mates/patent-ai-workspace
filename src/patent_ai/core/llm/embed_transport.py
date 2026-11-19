"""임베딩 전송층: 가짜·기록 전송층과 규약. 진짜(OpenAI) 전송층은 SDK가 있는 transport.py에."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from patent_ai.core.llm.errors import ModelConfigError, RecordingMissing
from patent_ai.core.llm.transport import (  # noqa: F401 (밖에서 여기로 가져다 씀)
    EmbedResponse,
    OpenAIEmbedTransport,
    TransportError,
    parse_openai_embeddings,
)


class EmbedTransport(Protocol):
    def embed(self, *, step: str, model: str, texts: list[str]) -> EmbedResponse: ...


@dataclass
class FakeEmbedTransport:
    """테스트용. 글 → 벡터 함수로 답하고, 받은 호출을 calls에 쌓는다.

    errors에 예외를 두면 앞 호출부터 차례로 그 예외를 낸다 (재시도 시험용).
    """

    vector_of: Callable[[str], list[float]]
    errors: list[Exception] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)

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
