"""단계 설정 읽기: step "<기능>.<단계>" -> config/<기능>.yaml 의 <단계> 칸."""

from dataclasses import dataclass
from pathlib import Path

import yaml

from patent_ai.core.llm.errors import ModelConfigError

# 저장소 루트 (src/patent_ai/core/llm/config.py 기준 네 단계 위)
REPO_ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class StepConfig:
    model: str
    temperature: float
    max_tokens: int
    prompt: str  # 저장소 루트 기준 경로 (prompts/...)
    price_per_mtok_input: float | None = None
    price_per_mtok_output: float | None = None


def load_step_config(step: str, config_dir: Path | None = None) -> StepConfig:
    feature, dot, name = step.partition(".")
    if not dot or not feature or not name:
        raise ModelConfigError(f"step은 '<기능>.<단계>' 모양이어야 함: {step!r}")
    path = (config_dir or REPO_ROOT / "config") / f"{feature}.yaml"
    if not path.is_file():
        raise ModelConfigError(f"설정 파일이 없음: {path} (step={step})")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    section = data.get(name)
    if not isinstance(section, dict):
        raise ModelConfigError(f"{path.name}에 단계 {name!r}이 없음 (step={step})")
    try:
        return StepConfig(
            model=section["model"],
            temperature=float(section["temperature"]),
            max_tokens=int(section["max_tokens"]),
            prompt=section["prompt"],
            price_per_mtok_input=section.get("price_per_mtok_input"),
            price_per_mtok_output=section.get("price_per_mtok_output"),
        )
    except KeyError as e:
        raise ModelConfigError(f"{step}에 설정 키가 빠짐: {e.args[0]}") from e
