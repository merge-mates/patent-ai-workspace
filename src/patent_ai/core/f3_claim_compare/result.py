"""F3 결과를 한데 담는 모델 (결과 스키마 v0 폴더 밖: 스키마에 아직 칸이 없는 것들).

검색 기록(SearchLogRow)에는 구성요소 원문을 싣지 않고 해시만 둔다.
못 찾은 질문(CQ) 목록은 여기서 만들지 않는다: 정답이 있어야 정해져서 채점기가 이 기록으로 만든다.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from patent_ai.core.schemas.case_materials import HeldTask
from patent_ai.core.schemas.common import Status
from patent_ai.core.schemas.comparison import ClarityReview, ComparisonTable
from patent_ai.core.schemas.judgment_unit import JudgmentUnit


class SearchLogRow(BaseModel):
    """검색 한 번의 기록: 어느 구성요소를 어느 인용문헌 안에서 찾았고 무엇이 걸렸나."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_id: str
    claim: int  # 대비 대상 청구항
    element_claim: int  # 구성요소가 실제로 있는 청구항 (부모에서 온 구성요소면 claim과 다르다)
    element_no: int  # element_claim 안의 순번
    element_hash: str  # 구성요소 글자의 sha256 앞 12자 (원문 아님)
    citation: str  # 라벨 D1…
    doc_id: str
    round: Literal[1, 2] = 1  # 2 = 한 번 더 찾기 (second_search)
    status: Status
    searched_scope: str  # 예: "D1 조각 120개 중 hybrid 상위 10 (cite-idx-v2)"
    hit_chunk_ids: list[str] = Field(default_factory=list)  # 순위 순서


class ExaminerLocationRow(BaseModel):
    """심사관이 짚은 위치 하나를 색인 조각과 맞춘 기록 (못 맞춘 것도 남긴다)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_id: str
    claim: int
    citation: str
    location: str  # F1 위치 값 그대로 (`[0016]`, `도 4`…)
    chunk_ids: list[str] = Field(default_factory=list)
    status: Status


class F3Result(BaseModel):
    """run_f3가 돌려주는 것 (조립은 진입 함수가 한다)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    oa_id: str
    units: list[JudgmentUnit] = Field(default_factory=list)
    comparisons: list[ComparisonTable] = Field(default_factory=list)
    clarity_reviews: list[ClarityReview] = Field(default_factory=list)
    held_tasks: list[HeldTask] = Field(default_factory=list)
    search_log: list[SearchLogRow] = Field(default_factory=list)
    examiner_locations: list[ExaminerLocationRow] = Field(default_factory=list)
    status: Status  # 안쪽 status 중 가장 나쁜 값
