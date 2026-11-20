"""F3 입력 모델: 설정 값(F3Settings)과 글자 입력(F3Inputs)을 한 객체(F3Config)에 싣는다.

도구(Tool.run)가 입력을 model_dump → model_validate로 왕복시키므로 모두 데이터(Pydantic)로만 둔다.
OA 당시 청구항 판을 고르는 일은 부르는 쪽이 한다 (F3는 받은 글자만 읽는다).
"""

from pydantic import BaseModel, ConfigDict, Field

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
    min_quote_chars: int = Field(ge=1)  # 정의 근거 글자 길이 하한 (짧은 글자 헛통과 막기)


class F3Settings(BaseModel):
    """config/f3.yaml에서 읽는 값. 단계별 모델 설정(model·effort 등)은 core/llm이 따로 읽는다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    impl: str  # 대비 방식 이름 (B8 전략 패턴)
    second_search: bool  # 못 찾은 구성요소를 한 번 더 찾을지 (B7)
    use_examiner_paragraphs: bool  # 심사관 지정 위치를 쓸지 (false = 평가 누출 막기)
    search: SearchSettings
    clarity_search: ClaritySearchSettings


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
