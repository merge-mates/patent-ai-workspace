"""단계 설정 읽기: step "<기능>.<단계>" -> config/<기능>.yaml 의 <단계> 칸."""

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from patent_ai.core.llm.errors import ModelConfigError

logger = logging.getLogger(__name__)

# 아는 설정 키 (상한·재시도는 limits와 client가 쓴다). 이 밖의 키는 오타로 보고 경고한다
KNOWN_KEYS = {
    "model",
    "effort",
    "max_tokens",
    "prompt",
    "price_per_mtok_input",
    "price_per_mtok_output",
    "max_model_calls",
    "max_input_tokens",
    "max_retries",
    "model_input",
    "search_k",  # f3.effect: 차이점마다 보여 줄 명세서 조각 수 (f3_claim_compare/config.py가 읽음)
}

# effort(output_config.effort)로 쓸 수 있는 값 (anthropic SDK 2.10.0 OutputConfigParam)
EFFORT_VALUES = ("low", "medium", "high", "xhigh", "max")

# 지금 API에서 빠진 키. 남아 있으면 그 값이 쓰이는 것처럼 읽히므로 조용히 넘기지 않고 멈춘다 (#134)
REMOVED_KEYS = {
    "temperature": "temperature는 API에서 빠져 보낼 수 없음. 지우고 effort를 쓴다",
    "top_p": "top_p는 API에서 빠져 보낼 수 없음. 지운다",
    "top_k": "top_k는 API에서 빠져 보낼 수 없음. 지운다",
}

# 저장소 루트 (src/patent_ai/core/llm/config.py 기준 네 단계 위)
REPO_ROOT = Path(__file__).resolve().parents[4]


@dataclass(frozen=True)
class StepConfig:
    model: str
    effort: str  # output_config.effort: low | medium | high | xhigh | max
    max_tokens: int
    prompt: str  # 저장소 루트 기준 경로 (prompts/...)
    price_per_mtok_input: float | None = None
    price_per_mtok_output: float | None = None
    # 상한·재시도. 설정에 없으면 None (상한 없음 / 다시 안 부름)
    max_model_calls: int | None = None
    max_input_tokens: int | None = None
    max_retries: int | None = None
    # 모델 입력 모양 (단계마다 다름, 값 검사는 그 단계 코드가 한다. 예: f1.read_oa의 raw·tables_md)
    model_input: str | None = None


def load_step_config(step: str, config_dir: Path | None = None) -> StepConfig:
    feature, dot, name = step.partition(".")
    if not dot or not feature or not name:
        raise ModelConfigError(f"step은 '<기능>.<단계>' 모양이어야 함: {step!r}")
    path = (config_dir or REPO_ROOT / "config") / f"{feature}.yaml"
    if not path.is_file():
        raise ModelConfigError(f"설정 파일이 없음: {path} (step={step})")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ModelConfigError(f"설정 파일 최상위가 dict가 아님: {path}")
    section = data.get(name)
    if not isinstance(section, dict):
        raise ModelConfigError(f"{path.name}에 단계 {name!r}이 없음 (step={step})")
    # 빠진 키(temperature 등)가 있으면 설정 읽기를 멈춘다
    for key, why in REMOVED_KEYS.items():
        if key in section:
            raise ModelConfigError(f"{step}: 설정 키 {key!r}를 지워야 함 ({why})")
    for key in section.keys() - KNOWN_KEYS:
        logger.warning("%s: 모르는 설정 키 %r (오타?)", step, key)
    for key in ("model", "effort", "max_tokens", "prompt"):
        if key not in section:
            raise ModelConfigError(f"{step}에 설정 키가 빠짐: {key}")
    # effort는 정해진 값만 받는다 (오타면 API가 400으로 끝나므로 미리 멈춤)
    if section["effort"] not in EFFORT_VALUES:
        raise ModelConfigError(
            f"{step}의 effort는 {'|'.join(EFFORT_VALUES)} 중 하나여야 함: {section['effort']!r}"
        )

    def number(key: str, kind):
        try:
            return kind(section[key])
        except (TypeError, ValueError) as e:
            raise ModelConfigError(f"{step}의 {key}를 숫자로 못 바꿈: {section[key]!r}") from e

    # 가격은 둘 다 있거나 둘 다 없어야 한다
    has_in = section.get("price_per_mtok_input") is not None
    has_out = section.get("price_per_mtok_output") is not None
    if has_in != has_out:
        raise ModelConfigError(
            f"{step}: price_per_mtok_input·output은 둘 다 있거나 둘 다 없어야 함"
        )
    if has_in:
        price_in = number("price_per_mtok_input", float)
        price_out = number("price_per_mtok_output", float)
    else:
        price_in = price_out = None
        logger.warning("%s: price(가격) 설정이 없어 비용을 계산하지 않음", step)
    limits = {}
    for key in ("max_model_calls", "max_input_tokens", "max_retries"):
        if section.get(key) is None:
            limits[key] = None
            continue
        limits[key] = number(key, int)
        if limits[key] < 0:
            raise ModelConfigError(f"{step}의 {key}는 0 이상이어야 함: {limits[key]}")
    return StepConfig(
        model=section["model"],
        effort=section["effort"],
        max_tokens=number("max_tokens", int),
        prompt=section["prompt"],
        price_per_mtok_input=price_in,
        price_per_mtok_output=price_out,
        model_input=section.get("model_input"),
        **limits,
    )
