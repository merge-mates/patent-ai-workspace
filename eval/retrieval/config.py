"""실험 설정(config.yaml) 읽기 (design.md 7-1 실험 설정). 공통 칸은 eval/common/config.py."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eval.common.config import BaseEvalConfig, load_yaml_config
from patent_ai.retrieval.schemas import Corpus, Mode


class Budget(BaseModel):
    # 칸 이름 오타로 상한이 조용히 빠지지 않게 모르는 칸은 막는다
    model_config = ConfigDict(extra="forbid")

    # 실험 config의 budget 칸 (틀: experiments/_template/config.yaml). 없는 칸은 상한 없음
    max_usd: float | None = None
    max_external_calls: int | None = None


class RetrievalEvalConfig(BaseEvalConfig):
    # 공통 칸(experiment·goldset·goldset_version·impl·settings) 위에 검색 전용 칸
    corpus: Corpus
    index_version: str
    mode: Mode
    k: list[int] = Field(min_length=1)
    gold: str  # <goldsets_root>/<goldset>/ 기준 상대 경로
    law_location_rule: str = "overlap_or_label"  # 법령만 (7-4)
    # 둘째 점수(이슈 #178): 줄마다 검색 범위 doc_id 목록 파일 (gold와 같은 기준 상대 경로).
    # 없으면 주 점수(그 인용문헌 안에서만). 만드는 법은 eval/retrieval/noise_scope.py
    noise_scope: str | None = None
    # 지금은 whole_doc_llm 채점만 지킨다 (다른 impl은 읽기만 하고 검사하지 않는다)
    budget: Budget | None = None

    @model_validator(mode="after")
    def _노이즈는_인용문헌만(self) -> RetrievalEvalConfig:
        if self.noise_scope is not None and self.corpus != "cite":
            raise ValueError("noise_scope는 cite 말뭉치에만 쓴다")
        return self


def load_config(path: str | Path) -> RetrievalEvalConfig:
    return load_yaml_config(path, RetrievalEvalConfig)
