"""OAResult(①): F1이 내는 OA 정리 결과. 모양의 기준은 docs/features/F1/design.md 3-2절."""

import logging
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from patent_ai.core.schemas.common import (
    ExtractedValue,
    Flag,
    ResultBase,
    Status,
    StatusValue,
    worst_status,
)

logger = logging.getLogger(__name__)

ALL_CHECKED = "모든 칸 원문 대조"  # 모두 confirmed일 때 결과 status의 checked


class NoticeKind(StrEnum):
    """통지 종류. 정답 형식(f1-oa-gold.md)과 같은 코드."""

    INITIAL = "initial"
    FINAL = "final"
    UNKNOWN = "unknown"  # 머리말을 못 읽음. 이때만 unverified


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True)

    number: ExtractedValue[str]
    country: str | None = None  # 못 정하면 null
    country_supported: bool
    cited_paragraphs: ExtractedValue[list[str]]
    flags: list[Flag] = Field(default_factory=list)

    @model_validator(mode="after")
    def _지원_안_하는_나라는_직접_검토(self) -> Citation:
        if not self.country_supported and Flag.NEEDS_HUMAN_REVIEW not in self.flags:
            raise ValueError("country_supported=false면 flags에 needs_human_review가 필요")
        return self


class Rejection(ResultBase):
    """거절이유 하나. 청구항은 거절이유마다 따로 둔다 (합치지 않음)."""

    article: ExtractedValue[str]
    supported: bool
    claims: ExtractedValue[list[int]]
    citations: list[Citation] = Field(default_factory=list)
    examiner_reasoning: ExtractedValue[str]

    @model_validator(mode="after")
    def _지원_안_하는_거절이유는_직접_검토(self) -> Rejection:
        if not self.supported and Flag.NEEDS_HUMAN_REVIEW not in self.flags:
            raise ValueError("supported=false면 flags에 needs_human_review가 필요")
        return self


class ExaminerHints(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowable_claims: ExtractedValue[list[int]]  # 「특허 가능한 청구항」. 칸이 없으면 값 []
    amendment_notes: ExtractedValue[str]  # 【보정에 관한 참고사항】. 칸이 없으면 값 null


class OAResult(ResultBase):
    model_config = ConfigDict(frozen=True)

    oa_id: str
    application_number: ExtractedValue[str]
    dispatch_number: ExtractedValue[str]
    notice_date: ExtractedValue[str]  # value는 비우고 raw_text만 (날짜 확정 안 함)
    response_due: ExtractedValue[str]  # 위와 같음
    notice_kind: ExtractedValue[NoticeKind]
    examined_claim_version: ExtractedValue[str] | None = None  # F1은 안 채움 (#16·#54)
    examiner_hints: ExaminerHints
    rejections: list[Rejection] = Field(default_factory=list)

    @model_validator(mode="after")
    def _모양_검사(self) -> OAResult:
        # 날짜·기한은 원문 글자만 둔다
        for name in ("notice_date", "response_due"):
            if getattr(self, name).value is not None:
                raise ValueError(f"{name}.value는 비워야 함 (원문 글자만)")
        # 통지 종류 unknown은 못 읽었다는 뜻이라 confirmed일 수 없다
        kind = self.notice_kind
        if kind.value == NoticeKind.UNKNOWN and kind.status.value != StatusValue.UNVERIFIED:
            raise ValueError("notice_kind=unknown이면 status는 unverified")
        return self


def summarize_rejection_status(rej: Rejection) -> Status:
    """거절이유 하나의 status: 그 안 칸들 중 가장 나쁜 값.

    지원 안 하는 나라 인용문헌은 상태를 나쁘게 하지 않는다 (flags로만).
    """
    statuses = [rej.article.status, rej.claims.status]
    for cit in rej.citations:
        if cit.country_supported:
            statuses += [cit.number.status, cit.cited_paragraphs.status]
    statuses.append(rej.examiner_reasoning.status)
    return worst_status(statuses, ALL_CHECKED)


def summarize_status(oa: OAResult) -> Status:
    """결과 전체 status: 칸들 중 가장 나쁜 값 (순서: 식별 정보 -> 통지 -> 거절이유 -> 힌트).

    지원 안 하는 거절이유(supported=false)는 빼고 모은다. 거절이유가 0개면
    unverified(not_extracted)로 두고 경고를 남긴다.
    """
    supported = [r for r in oa.rejections if r.supported]
    if not oa.rejections:
        logger.warning("OAResult %s: 거절이유 0개 -> unverified(not_extracted)", oa.oa_id)
        return worst_status([], ALL_CHECKED)
    statuses = [
        oa.application_number.status,
        oa.dispatch_number.status,
        oa.notice_date.status,
        oa.response_due.status,
        oa.notice_kind.status,
    ]
    if oa.examined_claim_version is not None:
        statuses.append(oa.examined_claim_version.status)
    statuses += [summarize_rejection_status(r) for r in supported]
    statuses += [
        oa.examiner_hints.allowable_claims.status,
        oa.examiner_hints.amendment_notes.status,
    ]
    return worst_status(statuses, ALL_CHECKED)
