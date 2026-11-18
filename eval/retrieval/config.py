"""실험 설정(config.yaml) 읽기 (design.md 7-1 실험 설정)."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from eval.retrieval.errors import RetrievalEvalError
from patent_ai.retrieval.schemas import Corpus, Mode


class RetrievalEvalConfig(BaseModel):
    # 모르는 키는 막지 않는다: 기존 틀의 baseline·budget 등이 같이 들어 있다
    model_config = ConfigDict(extra="ignore")

    experiment: str
    goldset: str
    goldset_version: int
    corpus: Corpus
    index_version: str
    mode: Mode
    impl: str
    k: list[int] = Field(min_length=1)
    gold: str  # <goldsets_root>/<goldset>/ 기준 상대 경로
    law_location_rule: str = "overlap_or_label"  # 법령만 (7-4)
    settings: dict = Field(default_factory=dict)  # 구현에 그대로 넘김


def load_config(path: str | Path) -> RetrievalEvalConfig:
    p = Path(path)
    if not p.is_file():
        raise RetrievalEvalError(f"설정 파일이 없다: {p.name}")
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RetrievalEvalError(f"설정 파일이 비었거나 모양이 틀리다: {p.name}")
    try:
        return RetrievalEvalConfig.model_validate(data)
    except ValidationError as e:
        names = sorted({str(err["loc"][0]) for err in e.errors() if err["loc"]})
        raise RetrievalEvalError(f"설정 파일 칸이 틀리다: {', '.join(names)}") from None
