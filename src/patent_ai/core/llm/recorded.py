"""기록된 모델 응답 전송층. 진짜 모델 답을 파일로 저장해 두고 테스트에서 다시 읽는다."""

import hashlib
import json
from pathlib import Path

from patent_ai.core.llm.errors import RecordingMissing
from patent_ai.core.llm.transport import TransportResponse


def recording_key(
    *,
    step: str,
    model: str,
    prompt: str,
    effort: str,
    max_tokens: int,
    system: str | None = None,
) -> str:
    """전송층이 받는 값(채워진 프롬프트 포함)의 sha256. 글자 하나만 달라도 다른 키.

    system은 있을 때만 넣는다 (없으면 system을 쓰기 전 기록 파일 키와 같다).
    """
    parts = dict(step=step, model=model, prompt=prompt, effort=effort, max_tokens=max_tokens)
    if system is not None:
        parts["system"] = system
    raw = json.dumps(parts, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def save_recording(
    directory: Path,
    resp: TransportResponse,
    *,
    step: str,
    model: str,
    prompt: str,
    effort: str,
    max_tokens: int,
) -> Path:
    """기록된 응답 파일 {"text","input_tokens","output_tokens","stop_reason","model","step"} 저장.

    이미 있으면 멈춘다.
    """
    key = recording_key(step=step, model=model, prompt=prompt, effort=effort, max_tokens=max_tokens)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{key}.json"
    if path.exists():
        raise FileExistsError(f"이미 기록된 응답이 있음: {path}")
    data = {
        "text": resp.text,
        "input_tokens": resp.input_tokens,
        "output_tokens": resp.output_tokens,
        "stop_reason": resp.stop_reason,
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
        self,
        *,
        step: str,
        model: str,
        prompt: str,
        effort: str,
        max_tokens: int,
        system: str | None = None,
    ) -> TransportResponse:
        key = recording_key(
            step=step,
            model=model,
            prompt=prompt,
            effort=effort,
            max_tokens=max_tokens,
            system=system,
        )
        path = self.directory / f"{key}.json"
        if not path.is_file():
            raise RecordingMissing(
                f"기록된 응답이 없음: {path} (step={step}). scripts/record_llm.py로 기록"
            )
        d = json.loads(path.read_text(encoding="utf-8"))
        # stop_reason 칸이 없는 옛 기록 파일은 None으로 읽는다
        return TransportResponse(
            d["text"], d["input_tokens"], d["output_tokens"], d.get("stop_reason")
        )
