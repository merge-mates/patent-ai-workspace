"""F1 실험 설정. 공통 칸 위에 정답 폴더만 더한다."""

from pathlib import Path

from eval.common.config import BaseEvalConfig, load_yaml_config


class F1EvalConfig(BaseEvalConfig):
    gold: str = "f1"  # <goldsets_root>/<goldset>/ 아래 정답 폴더


def load_config(path: str | Path) -> F1EvalConfig:
    return load_yaml_config(path, F1EvalConfig)
