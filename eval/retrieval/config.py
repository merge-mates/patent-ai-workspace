"""실험 설정(config.yaml) 읽기 (design.md 7-1 실험 설정). 공통 칸은 eval/common/config.py."""

from pathlib import Path

from pydantic import Field

from eval.common.config import BaseEvalConfig, load_yaml_config
from patent_ai.retrieval.schemas import Corpus, Mode


class RetrievalEvalConfig(BaseEvalConfig):
    # 공통 칸(experiment·goldset·goldset_version·impl·settings) 위에 검색 전용 칸
    corpus: Corpus
    index_version: str
    mode: Mode
    k: list[int] = Field(min_length=1)
    gold: str  # <goldsets_root>/<goldset>/ 기준 상대 경로
    law_location_rule: str = "overlap_or_label"  # 법령만 (7-4)


def load_config(path: str | Path) -> RetrievalEvalConfig:
    return load_yaml_config(path, RetrievalEvalConfig)
