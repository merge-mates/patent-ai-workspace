"""F4 스위치·상한 읽기: config/f4.yaml 맨 위 칸.

단계 칸(model·effort·prompt·max_model_calls)은 core/llm의 load_step_config가 읽는다.
여기서는 그 함수가 읽지 않는 값만 읽고, 형이 틀리면 조용히 기본값으로 넘어가지 않고 멈춘다.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

from patent_ai.core.llm.config import REPO_ROOT
from patent_ai.core.llm.errors import ModelConfigError


@dataclass(frozen=True)
class F4Options:
    final_rejection_limit: bool  # 최후거절이유통지 보정 제한 스위치 (동작은 보정 초안 단계)
    max_units: int  # 한 실행에서 다루는 판단 단위 수 상한
    max_candidates: int  # 묶음 하나의 방향 후보 수 상한
    # 보정 근거 글자(띄어쓰기 뺀 길이) 하한. 설정 파일에서는 꼭 적는다 (기본값은 코드에서 만들 때만)
    min_basis_chars: int = 10


def load_f4_options(config_dir: Path | None = None) -> F4Options:
    path = (config_dir or REPO_ROOT / "config") / "f4.yaml"
    if not path.is_file():
        raise ModelConfigError(f"설정 파일이 없음: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ModelConfigError(f"설정 파일 최상위가 dict가 아님: {path}")

    def read(key: str):
        if key not in data:
            raise ModelConfigError(f"f4.yaml에 설정 키가 빠짐: {key}")
        return data[key]

    switch = read("final_rejection_limit")
    if not isinstance(switch, bool):
        raise ModelConfigError(f"final_rejection_limit은 true·false여야 함: {switch!r}")

    def positive(key: str) -> int:
        value = read(key)
        # bool은 int의 하위 형이라 따로 막는다 (true가 1로 읽히지 않게)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ModelConfigError(f"{key}는 1 이상의 정수여야 함: {value!r}")
        return value

    return F4Options(
        final_rejection_limit=switch,
        max_units=positive("max_units"),
        max_candidates=positive("max_candidates"),
        min_basis_chars=positive("min_basis_chars"),
    )
