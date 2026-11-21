"""F3 입력 모델: 설정 값(F3Settings)과 글자 입력(F3Inputs)을 한 객체(F3Config)에 싣는다.

도구(Tool.run)가 입력을 model_dump → model_validate로 왕복시키므로 모두 데이터(Pydantic)로만 둔다.
OA 당시 청구항 판을 고르는 일은 부르는 쪽이 한다 (F3는 받은 글자만 읽는다).
"""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from patent_ai.core.schemas.common import Status
from patent_ai.core.schemas.document import PageText


class HybridSettings(BaseModel):
    """RRF로 섞는 값 (retrieval/hybrid.py가 읽는 모양 그대로)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rrf_k: int = Field(ge=1)
    weights: dict[str, float]


class SearchSettings(BaseModel):
    """인용문헌 문단 검색 설정 (config/f3.yaml search 칸)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    impl: str  # 검색 구현 이름 (retrieval/<이름>.py)
    index_version: str  # 색인 판
    k: int = Field(ge=1)  # 구성요소마다 가져올 상위 조각 수
    tokenizer: str
    pos_tags: list[str]
    bm25: dict[str, str | float]
    hybrid: HybridSettings

    def searcher_settings(self) -> dict:
        """retrieval.contract.get_searcher에 넘길 settings dict (impl·k는 따로 넘긴다)."""
        return self.model_dump(exclude={"impl", "k"})


class ClaritySearchSettings(BaseModel):
    """명확성: 그 사건 출원서 안에서 용어 정의를 찾는 값 (config/f3.yaml clarity_search 칸)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    k: int = Field(ge=1)  # 문구마다 모델에 보여 줄 명세서 조각 수 (BM25 상위)
    # 정의 찾기 색인에서 뺄 구간의 머리 줄 꼴 (청구범위·요약서·도면). 공백·괄호를 뺀 글자에 맞춘다
    skip_headings: list[str]


class F3Settings(BaseModel):
    """config/f3.yaml에서 읽는 값. 단계별 모델 설정(model·effort 등)은 core/llm이 따로 읽는다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    impl: str  # 대비 방식 이름 (B8 전략 패턴)
    second_search: bool  # 못 찾은 구성요소를 한 번 더 찾을지 (B7)
    second_search_depth: int = Field(ge=2)  # 한 번 더 찾을 때 받는 상위 조각 수 (1차 k보다 커야 함)
    use_examiner_paragraphs: bool  # 심사관 지정 위치를 쓸지 (false = 평가 누출 막기)
    # 모델이 근거로 옮긴 글자(공백 뺀 뒤)의 길이 하한. 한두 글자는 아무 조각에나 맞아 받지 않는다
    min_quote_chars: int = Field(ge=1)
    search: SearchSettings
    clarity_search: ClaritySearchSettings
    # 효과 후보: 차이점마다 모델에 보여 줄 최초 명세서 조각 수 (config/f3.yaml effect.search_k)
    effect_search_k: int = Field(ge=1)

    @model_validator(mode="after")
    def _두_번째_검색은_더_깊어야_함(self) -> F3Settings:
        # 1차 k 이하면 새 조각이 하나도 안 나와 "두 번 찾음"이 거짓이 된다
        if self.second_search_depth <= self.search.k:
            raise ValueError("second_search_depth는 search.k보다 커야 함")
        return self


class F3Inputs(BaseModel):
    """F3가 읽는 글자. 부르는 쪽(테스트·실행 스크립트)이 만들어 준다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claims_at_oa: dict[int, str]  # OA 당시 청구항: 번호 -> 원문 글자
    # 그 청구항이 OA 당시 판이 맞는지. confirmed가 아니면 뒤 결과는 input_unverified
    claims_status: Status
    claims_document_id: str  # 청구항 글자가 나온 문서 ID
    spec: PageText | None = None  # 최초 명세서 쪽 글자 (명확성 단계가 씀). 없으면 None


class F3Config(BaseModel):
    """run_f3에 넘기는 설정 하나: yaml 값 + 글자 입력."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    settings: F3Settings
    inputs: F3Inputs
