"""모델 답 캐시. 같은 입력이면 전송층을 다시 부르지 않는다."""

import hashlib
import json
from pathlib import Path
from typing import Protocol

from patent_ai.core.llm.config import REPO_ROOT

# 기본 캐시 폴더 (work/는 git 밖)
DEFAULT_CACHE_DIR = REPO_ROOT / "work" / "llm_cache"


def make_cache_key(
    *,
    step: str,
    model: str,
    prompt_template: str,
    variables: dict,
    effort: str,
    max_tokens: int,
    attempt: int,
) -> str:
    """(단계, 모델, 프롬프트 파일 내용 해시, 변수, 설정 값, attempt)의 sha256.

    하나라도 바뀌면 다른 키가 된다.
    """
    parts = {
        "step": step,
        "model": model,
        "prompt_sha256": hashlib.sha256(prompt_template.encode("utf-8")).hexdigest(),
        "variables": variables,
        "effort": effort,
        "max_tokens": max_tokens,
        "attempt": attempt,
    }
    # 변수가 JSON으로 안 바뀌면 TypeError (호출한 쪽에서 설정 오류로 바꿈)
    raw = json.dumps(parts, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Cache(Protocol):
    def get(self, key: str) -> dict | None: ...

    def put(self, key: str, value: dict) -> None: ...


class MemoryCache:
    """테스트용 메모리 캐시."""

    def __init__(self) -> None:
        self._data: dict[str, dict] = {}

    def get(self, key: str) -> dict | None:
        return self._data.get(key)

    def put(self, key: str, value: dict) -> None:
        self._data[key] = value


class FileCache:
    """키 하나 = JSON 파일 하나."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = Path(directory or DEFAULT_CACHE_DIR)

    def get(self, key: str) -> dict | None:
        path = self.directory / f"{key}.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def put(self, key: str, value: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / f"{key}.json").write_text(
            json.dumps(value, ensure_ascii=False), encoding="utf-8"
        )
