"""녹화 응답 전송층. 진짜 모델 답을 파일로 저장해 두고 테스트에서 다시 읽는다."""

import hashlib
import json
from pathlib import Path

from patent_ai.core.llm.errors import RecordingMissing
from patent_ai.core.llm.transport import TransportResponse


def recording_key(
    *, step: str, model: str, prompt: str, temperature: float, max_tokens: int
) -> str:
    """전송층이 받는 값(채워진 프롬프트 포함)의 sha256. 글자 하나만 달라도 다른 키."""
    parts = dict(
        step=step, model=model, prompt=prompt, temperature=temperature, max_tokens=max_tokens
    )
    raw = json.dumps(parts, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def save_recording(
    directory: Path,
    resp: TransportResponse,
    *,
    step: str,
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
) -> Path:
    """녹화 파일 {"text","input_tokens","output_tokens","model","step"} 저장. 이미 있으면 멈춘다."""
    key = recording_key(
        step=step, model=model, prompt=prompt, temperature=temperature, max_tokens=max_tokens
    )
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{key}.json"
    if path.exists():
        raise FileExistsError(f"이미 녹화가 있음: {path}")
    data = {
        "text": resp.text,
        "input_tokens": resp.input_tokens,
        "output_tokens": resp.output_tokens,
        "model": model,
        "step": step,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


class RecordedTransport:
    """저장한 답만 돌려준다. 없으면 RecordingMissing (진짜 호출로 넘어가지 않음)."""

    is_real = False  # 돈 안 드는 전송층 (is_real_transport)

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def complete(
        self, *, step: str, model: str, prompt: str, temperature: float, max_tokens: int
    ) -> TransportResponse:
        key = recording_key(
            step=step, model=model, prompt=prompt, temperature=temperature, max_tokens=max_tokens
        )
        path = self.directory / f"{key}.json"
        if not path.is_file():
            raise RecordingMissing(
                f"녹화가 없음: {path} (step={step}). scripts/record_llm.py로 녹화"
            )
        d = json.loads(path.read_text(encoding="utf-8"))
        return TransportResponse(d["text"], d["input_tokens"], d["output_tokens"])
