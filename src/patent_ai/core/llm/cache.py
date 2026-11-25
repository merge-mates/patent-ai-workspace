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
    system_template: str | None = None,
) -> str:
    """(단계, 모델, 프롬프트 파일 내용 해시, 변수, 설정 값, attempt)의 sha256.

    하나라도 바뀌면 다른 키가 된다. system 프롬프트가 있으면 그 해시도 넣는다
    (없으면 칸을 아예 넣지 않아 system을 쓰기 전 캐시 키와 같다).
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
    if system_template is not None:
        parts["system_sha256"] = hashlib.sha256(system_template.encode("utf-8")).hexdigest()
    # 변수가 JSON으로 안 바뀌면 TypeError (호출한 쪽에서 설정 오류로 바꿈)
    raw = json.dumps(parts, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def make_turn_cache_key(
    *,
    step: str,
    model: str,
    prompt_template: str,
    system_variables: dict,
    messages: list[dict],
    tools: list[dict],
    effort: str,
    max_tokens: int,
) -> str:
    """tool use 한 차례의 캐시 키 (sha256). make_cache_key와 같은 꼴에 messages·tools를 더했다.

    "kind": "turn"을 넣어 한 번 부르는 호출(make_cache_key)의 키와 섞이지 않게 한다.
    하나라도 바뀌면 다른 키가 된다 (messages 글자 하나, tools 한 칸도).
    """
    parts = {
        "kind": "turn",
        "step": step,
        "model": model,
        "prompt_sha256": hashlib.sha256(prompt_template.encode("utf-8")).hexdigest(),
        "system_variables": system_variables,
        "messages": messages,
        "tools": tools,
        "effort": effort,
        "max_tokens": max_tokens,
    }
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
