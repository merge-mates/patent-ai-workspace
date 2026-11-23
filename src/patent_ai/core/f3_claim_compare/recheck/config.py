"""config/recheck.yaml의 근거 다시 찾기 설정 읽기.

단계 칸(rewrite·agent)은 core/llm의 load_step_config가 읽는다. 여기서는 설정 칸 목록만 읽는다
(load_f3_settings와 같은 규칙: 칸이 빠지면 기본값으로 때우지 않고 멈춘다).
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from patent_ai.core.llm.config import REPO_ROOT
from patent_ai.core.llm.errors import ModelConfigError


class RecheckLimits(BaseModel):
    """에이전트 한 번의 상한."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_calls: int = Field(ge=1)
    turns: int = Field(ge=1)


class RecheckSearch(BaseModel):
    """다시 찾기 검색 값."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    k_max: int = Field(ge=1)  # 도구 한 번이 돌려줄 최대 조각 수
    snippet_chars: int = Field(ge=1)  # 도구가 보여 주는 앞부분 글자 수
    rewrite_k: int = Field(ge=1)  # 고정 루프: 질의마다 받는 상위 조각 수
    rewrite_n: int = Field(ge=1)  # 고정 루프: 다시 쓸 질의 수


class RecheckSettings(BaseModel):
    """다시 찾기 설정. 기본값(recheck=none)이면 F3는 옛 동작 그대로다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    recheck: Literal["none", "fixed_loop", "agent"] = "none"
    recheck_judge: Literal["compare", "agent"] = "compare"
    reflect: Literal[0, 1] = 0
    supervisor: Literal["code", "llm"] = "code"
    spec_basis: Literal["none", "fixed_loop", "agent"] = "none"
    limits: RecheckLimits = RecheckLimits(tool_calls=8, turns=10)
    search: RecheckSearch = RecheckSearch(k_max=10, snippet_chars=160, rewrite_k=10, rewrite_n=3)


# 이 파일이 읽는 맨 위 칸. 그 밖의 칸(rewrite·agent)은 단계 설정이라 core/llm 몫
_SETTING_KEYS = (
    "recheck",
    "recheck_judge",
    "reflect",
    "supervisor",
    "spec_basis",
    "limits",
    "search",
)


def _check_implemented(s: RecheckSettings) -> None:
    """아직 구현 안 된 값은 조용히 무시하지 않고 멈춘다 (켠 값이 안 돌고 넘어가지 않게)."""
    if s.reflect != 0:
        raise ModelConfigError("recheck.yaml reflect: 1은 아직 구현 안 됨 (0만)")
    if s.supervisor != "code":
        raise ModelConfigError("recheck.yaml supervisor: llm은 아직 구현 안 됨 (code만)")
    if s.spec_basis != "none":
        raise ModelConfigError(
            f"recheck.yaml spec_basis: {s.spec_basis}는 아직 구현 안 됨 (none만)"
        )


def load_recheck_settings(config_dir: Path | None = None) -> RecheckSettings:
    path = (config_dir or REPO_ROOT / "config") / "recheck.yaml"
    if not path.is_file():
        raise ModelConfigError(f"설정 파일이 없음: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ModelConfigError(f"설정 파일 최상위가 dict가 아님: {path}")
    missing = [key for key in _SETTING_KEYS if key not in data]
    if missing:
        raise ModelConfigError(f"{path.name}에 설정 칸이 빠짐: {missing}")
    try:
        settings = RecheckSettings.model_validate({key: data[key] for key in _SETTING_KEYS})
    except ValidationError as e:
        raise ModelConfigError(f"{path.name} 설정 값이 잘못됨: {e}") from e
    _check_implemented(settings)
    return settings
