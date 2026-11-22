"""사건 자료·보류 목록(⑥ CaseMaterials)의 F1 칸. 모양의 기준은 docs/features/F1/design.md 3-2절.

채우는 쪽은 #16·#54, 여기서는 모양과 검사만 둔다.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from patent_ai.core.schemas.common import Status


class LookupResult(StrEnum):
    """빠진 자료를 조회한 결과."""

    LOOKUP_FAILED = "lookup_failed"  # 조회 실패
    BODY_MISSING = "body_missing"  # 본문 없음
    UNSUPPORTED_COUNTRY = "unsupported_country"  # 지원 안 하는 나라 (직접 확인)


class CaseDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str
    kind: str  # 예: oa, claims, citation
    source: str  # uploaded | api
    # 묶기 상태 (#16 GroupedMaterial.status). 다른 출원번호(conflict)·번호 못 읽음(unverified)
    # 자료가 어느 문서인지 다시 열어도 남게 한다. 빼는 것은 cut_to_oa(#54)
    status: Status
    # 글자 추출 상태 (PageText.status). 스캔본이면 unverified(body_missing). 묶기 status와 합치지
    # 않는다: 합치면 원인(글자 없음)이 묶기 결과에 가려진다. 모르면 None (#140)
    text_status: Status | None = None
    # 인용문헌 본문이면 어느 인용문헌인지: OA 인용문헌 번호 값(Citation.number.value, 예
    # "US20990000001A1"). F3가 이 키로 본문 문서를 찾는다 (#201). 다른 종류이거나 모르면 None
    citation_key: str | None = None


class MissingMaterial(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    what: str
    depends_on_tasks: list[str] = Field(default_factory=list)
    lookup_result: LookupResult
    ask_upload: bool
    # 빠진 인용문헌의 번호 키 (CaseDocument.citation_key와 같은 꼴). 번호를 못 읽었으면 None.
    # 올린 문서가 이 키를 받아 다시 열어도 어느 인용문헌 답인지 남는다 (#201)
    citation_key: str | None = None

    @model_validator(mode="after")
    def _지원_안_하는_나라는_올려_달라고_안_함(self) -> MissingMaterial:
        # 한국·미국 밖 인용문헌은 "지원 안 함, 직접 확인"이라 "올려 주세요"를 띄우지 않는다
        if self.lookup_result == LookupResult.UNSUPPORTED_COUNTRY and self.ask_upload:
            raise ValueError("지원 안 하는 나라는 ask_upload=true일 수 없음")
        return self


class HeldTask(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task: str
    waiting_for: str


ReviewKind = Literal[
    "unverified",
    "conflict",
    "needs_recheck",
    "needs_human_judgment",
    "needs_human_review",
    "missing_material",
]


# propagation.py가 이 파일을 import하므로 ReviewItem 정의는 여기에 둔다 (거꾸로 두면 순환).
class ReviewItem(BaseModel):
    """사람이 봐야 할 것 하나."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ReviewKind
    # 결과 안 경로. 예: oa_result[oa_1].rejections[0].citations[1].country, materials.missing[0]
    target: str
    label: str  # 사람이 읽는 이름. 예: 조문 "42-3", 인용문헌 번호, 빠진 자료 이름
    reason: str  # 왜. 예: not_extracted, "지원 안 하는 거절이유 42-3"


class CaseMaterials(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    documents: list[CaseDocument] = Field(default_factory=list)
    missing: list[MissingMaterial] = Field(default_factory=list)
    held_tasks: list[HeldTask] = Field(default_factory=list)
    review_items_count: int = Field(default=0, ge=0)
    # 검토할 사항 목록. None = 아직 마무리(모으기)를 안 한 ⑥ (저장소가 저장을 거부한다).
    # 빈 목록 []은 "마무리했고 0건"이라 None과 다르다
    review_items: list[ReviewItem] | None = None

    @model_validator(mode="after")
    def _개수는_목록_줄_수와_같다(self) -> CaseMaterials:
        # N(화면에 보이는 개수) = 목록 줄 수. 목록이 없으면 개수도 0이어야 한다
        expected = len(self.review_items) if self.review_items is not None else 0
        if self.review_items_count != expected:
            raise ValueError(
                f"review_items_count({self.review_items_count})가 "
                f"review_items 줄 수({expected})와 다름"
            )
        return self
