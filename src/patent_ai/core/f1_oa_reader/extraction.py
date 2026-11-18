"""모델이 돌려주는 출력 스키마 OAExtraction (design.md 3-2).

값마다 {value, raw_text, page, ambiguous}만 둔다. 상태·supported·country·flags는 없다:
상태는 원문 대조 결과라 코드가 정한다 (모델이 몰래 넣으면 검사에서 떨어짐).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict


class Item(BaseModel):
    """모델이 뽑은 값 하나. 원문 글자와 쪽을 같이 받는다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: Any | None = None
    raw_text: str | None = None
    page: int | None = None
    ambiguous: bool = False


class CitationExtraction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    number: Item | None = None
    cited_paragraphs: Item | None = None  # 식별번호가 없으면 null


class RejectionExtraction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    article: Item | None = None
    claims: Item | None = None
    citations: list[CitationExtraction] = []
    examiner_reasoning: Item | None = None  # value=요지, raw_text=원문


class OAExtraction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    application_number: Item | None = None
    dispatch_number: Item | None = None
    examined_claims: Item | None = None  # 심사 대상 청구항 (원문 글자, 예: 제1항 내지 제20항)
    rejections: list[RejectionExtraction]
    allowable_claims: Item | None = None  # 칸이 없으면 null
    amendment_note: Item | None = None  # 칸이 없으면 null
