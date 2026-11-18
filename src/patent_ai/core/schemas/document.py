"""문서 쪽 글자 스키마: Page, PageText. 모양의 기준은 docs/features/F1/design.md."""

from pydantic import BaseModel, ConfigDict, Field

from patent_ai.core.schemas.common import Status


class Page(BaseModel):
    """쪽 하나의 글자. 쪽 번호는 1부터. status는 그 쪽에 글자가 있는지."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    page: int = Field(ge=1)
    text: str
    status: Status


class PageText(BaseModel):
    """문서 한 건의 쪽별 글자와 문서 전체 status."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str
    pages: list[Page]
    status: Status
