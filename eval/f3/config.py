"""F3 실험 설정. 공통 칸 위에 정답 경로와 색인 판을 더한다."""

from pathlib import Path

from eval.common.config import BaseEvalConfig, load_yaml_config


class F3EvalConfig(BaseEvalConfig):
    index_version: str  # 예측이 찾은 조각의 색인 판 (조각 위치를 읽어 정답과 맞춘다)
    k: int = 10  # 예측을 만들 때 쓴 검색 상위 k (기록용)
    cite_gold: str = "retrieval/cite_gold.jsonl"  # <goldsets_root>/<goldset>/ 기준
    f1_gold: str = "f1"  # 명확성 표현(clarity_terms) 정답 폴더


def load_config(path: str | Path) -> F3EvalConfig:
    return load_yaml_config(path, F3EvalConfig)
