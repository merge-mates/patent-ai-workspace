"""config/f3.yaml의 F3 설정(스위치·검색 값) 읽기.

단계별 모델 설정(split_elements 등)은 core/llm/config.py의 load_step_config가 읽는다.
칸이 빠지면 기본값으로 때우지 않고 멈춘다 (실험 값이 조용히 바뀌지 않게).
"""

from pathlib import Path

import yaml
from pydantic import ValidationError

from patent_ai.core.f3_claim_compare.inputs import F3Settings
from patent_ai.core.llm.config import REPO_ROOT
from patent_ai.core.llm.errors import ModelConfigError

# F3Settings가 읽는 맨 위 칸. 그 밖의 맨 위 칸은 단계 설정(core/llm 몫)이라 여기서 보지 않는다
_SETTING_KEYS = (
    "impl",
    "second_search",
    "second_search_depth",
    "use_examiner_paragraphs",
    "min_quote_chars",
    "search",
    "clarity_search",
    "effect_search",
)


def load_f3_settings(config_dir: Path | None = None) -> F3Settings:
    path = (config_dir or REPO_ROOT / "config") / "f3.yaml"
    if not path.is_file():
        raise ModelConfigError(f"설정 파일이 없음: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ModelConfigError(f"설정 파일 최상위가 dict가 아님: {path}")
    missing = [key for key in _SETTING_KEYS if key not in data]
    if missing:
        raise ModelConfigError(f"{path.name}에 설정 칸이 빠짐: {missing}")
    try:
        return F3Settings.model_validate({key: data[key] for key in _SETTING_KEYS})
    except ValidationError as e:
        raise ModelConfigError(f"{path.name} 설정 값이 잘못됨: {e}") from e
