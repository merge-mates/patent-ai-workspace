"""문서 쪽 글자 스키마: Page, PageText. 모양의 기준은 docs/features/F1/design.md."""

from pydantic import BaseModel, ConfigDict, Field

from patent_ai.core.schemas.common import Status


class Page(BaseModel):
    """쪽 하나의 글자와 표. 쪽 번호는 1부터. status는 그 쪽에 글자가 있는지."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    page: int = Field(ge=1)
    text: str
    status: Status
    # 그 쪽의 표들: 표마다 행, 행마다 칸 글자 (빈 칸은 ""). 표가 없으면 빈 목록.
    # 기본값이 빈 목록이라 tables가 없는 예전 JSON도 그대로 읽힌다.
    tables: list[list[list[str]]] = Field(default_factory=list)


class PageText(BaseModel):
    """문서 한 건의 쪽별 글자와 문서 전체 status."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str
    pages: list[Page]
    status: Status
