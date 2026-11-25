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
    # 보정 프롬프트 명세서 글자를 겹치는 문단 상위 N개로 줄이는 스위치 (기본 끔 = 쪽 글자 전체)
    spec_excerpt_enabled: bool = False
    spec_excerpt_top_n: int = 5
    # 켜면 보정 초안을 먼저 만들고, 의견서(f4.opinion_amended)가 그 보정 결과와
    # F1 항별 심사관 근거를 받는다. 끄면(기본) 방향 → 의견서 → 보정 순서 그대로
    # (m3-i2-opinion-amend 실험 스위치)
    opinion_after_amendment: bool = False
    # 끄면 보정안 단계(f4.amendment)를 부르지 않고, 의견서는 바깥 보정 결과
    # (F4Input.external_amendment)로 묶음마다 반박 + 사건 전체 한 번으로 쓴다 (11/26 P5)
    amendment_enabled: bool = True


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

    max_units = positive("max_units")
    # 묶음마다 첫 호출 + 출력 검사 실패 때 한 번. 단계 상한이 이보다 작으면 묶음이 많은 사건이
    # 중간에 끊긴다. 돌리다 끊기지 않게 설정을 읽을 때 멈춘다
    for step in ("direction", "opinion", "opinion_amended", "opinion_unit", "amendment"):
        section = data.get(step)
        limit = section.get("max_model_calls") if isinstance(section, dict) else None
        if isinstance(limit, int) and not isinstance(limit, bool) and limit < 2 * max_units:
            raise ModelConfigError(
                f"f4.{step}의 max_model_calls {limit}가 2 × max_units({max_units})보다 작음"
            )
    excerpt = _read_spec_excerpt(data.get("amendment_spec_excerpt"))
    # 칸이 없으면 끔. 있으면 true·false만 받는다 (오타가 조용히 끔이 되지 않게)
    after = data.get("opinion_after_amendment", False)
    if not isinstance(after, bool):
        raise ModelConfigError(f"opinion_after_amendment는 true·false여야 함: {after!r}")
    enabled = data.get("amendment_enabled", True)
    if not isinstance(enabled, bool):
        raise ModelConfigError(f"amendment_enabled는 true·false여야 함: {enabled!r}")
    return F4Options(
        amendment_enabled=enabled,
        final_rejection_limit=switch,
        max_units=max_units,
        max_candidates=positive("max_candidates"),
        min_basis_chars=positive("min_basis_chars"),
        spec_excerpt_enabled=excerpt[0],
        spec_excerpt_top_n=excerpt[1],
        opinion_after_amendment=after,
    )


def _read_spec_excerpt(section) -> tuple[bool, int]:
    """amendment_spec_excerpt 칸. 칸이 없으면 끔. 있으면 모양·값이 맞아야 하고 틀리면 멈춘다."""
    if section is None:
        return False, F4Options.spec_excerpt_top_n
    if not isinstance(section, dict):
        raise ModelConfigError(f"amendment_spec_excerpt는 enabled·top_n 칸이어야 함: {section!r}")
    unknown = sorted(set(section) - {"enabled", "top_n"})
    if unknown:
        raise ModelConfigError(f"amendment_spec_excerpt에 모르는 키: {unknown}")
    for key in ("enabled", "top_n"):
        if key not in section:
            raise ModelConfigError(f"amendment_spec_excerpt에 설정 키가 빠짐: {key}")
    enabled, top_n = section["enabled"], section["top_n"]
    if not isinstance(enabled, bool):
        raise ModelConfigError(f"amendment_spec_excerpt.enabled는 true·false여야 함: {enabled!r}")
    # bool은 int의 하위 형이라 따로 막는다. 끄더라도 값이 틀리면 멈춘다 (켤 때 처음 터지지 않게)
    if isinstance(top_n, bool) or not isinstance(top_n, int) or top_n < 1:
        raise ModelConfigError(f"amendment_spec_excerpt.top_n은 1 이상의 정수여야 함: {top_n!r}")
    return enabled, top_n
