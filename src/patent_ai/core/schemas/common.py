"""결과 공통 칸: 상태(Status), 근거(Evidence), 추출 값(ExtractedValue), 결과 바탕(ResultBase).

모양의 기준은 docs/features/F1/design.md 3-2절. 값은 모두 영어 코드(str 기반 enum)다.
"""

import logging
from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


class StatusValue(StrEnum):
    """상태 네 값. 이 밖의 값은 저장 전에 거부한다."""

    CONFIRMED = "confirmed"  # 확인됨
    UNVERIFIED = "unverified"  # 확인되지 않음
    NOT_FOUND_IN_SCOPE = "not_found_in_scope"  # 조회 범위 내 없음
    CONFLICT = "conflict"  # 충돌


class UnverifiedReason(StrEnum):
    """`unverified`일 때 왜 확인되지 않았나."""

    LOOKUP_FAILED = "lookup_failed"
    BODY_MISSING = "body_missing"
    EDITION_UNKNOWN = "edition_unknown"
    NOT_EXTRACTED = "not_extracted"
    AMBIGUOUS = "ambiguous"
    INPUT_UNVERIFIED = "input_unverified"  # 기대는 앞 입력이 확인되지 않음


class Origin(StrEnum):
    AI_GENERATED = "ai_generated"
    AI_DEFAULT = "ai_default"
    HUMAN_SELECTED = "human_selected"
    HUMAN_EDITED = "human_edited"


class Flag(StrEnum):
    NEEDS_HUMAN_JUDGMENT = "needs_human_judgment"  # 직접 판단 필요
    NEEDS_HUMAN_REVIEW = "needs_human_review"  # 직접 검토 필요


class Status(BaseModel):
    """상태 객체. 직렬화하면 늘 네 키(없는 키는 null)."""

    value: StatusValue
    reason: UnverifiedReason | None = None
    checked: str | None = None  # confirmed: 무엇을 확인했나
    searched_scope: str | None = None  # not_found_in_scope: 어디까지 찾았나

    @model_validator(mode="after")
    def _값에_맞는_칸만_채운다(self) -> Status:
        v = self.value
        # 값마다 필수 칸이 있고, 그 값에 맞지 않는 칸은 비워 둬야 한다
        if (v == StatusValue.UNVERIFIED) != (self.reason is not None):
            raise ValueError("reason은 unverified일 때만, 그리고 unverified면 꼭 채운다")
        if (v == StatusValue.CONFIRMED) != (self.checked is not None):
            raise ValueError("checked는 confirmed일 때만, 그리고 confirmed면 꼭 채운다")
        if (v == StatusValue.NOT_FOUND_IN_SCOPE) != (self.searched_scope is not None):
            raise ValueError("searched_scope는 not_found_in_scope일 때만, 그리고 그때는 꼭 채운다")
        return self


class Evidence(BaseModel):
    """근거 위치. 화면이 그 쪽 text에서 raw_text를 찾아 강조한다."""

    document_id: str
    page: int | None = None
    raw_text: str | None = None
    edition: str | None = None  # 법령·심사기준 판본
    checked_on: date | None = None


class ResultBase(BaseModel):
    """모든 결과 스키마가 갖는 공통 칸."""

    status: Status
    evidence: list[Evidence] = Field(default_factory=list)
    origin: Origin = Origin.AI_GENERATED
    needs_recheck: bool = False  # status 값이 아니라 별도 칸
    recheck_reason: str | None = None
    flags: list[Flag] = Field(default_factory=list)


class Candidate[T](BaseModel):
    """충돌 때 남기는 후보 하나 (규칙 값 / 모델 값)."""

    value: T | None = None
    raw_text: str | None = None
    page: int | None = None
    source: Literal["rule", "model"]


class ExtractedValue[T](BaseModel):
    """원문에서 뽑은 값 하나. 값에는 늘 원문 글자·쪽·상태가 붙는다."""

    value: T | None = None
    raw_text: str | None = None
    page: int | None = None
    status: Status
    candidates: list[Candidate[Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _후보는_충돌일_때만(self) -> ExtractedValue[T]:
        if self.status.value == StatusValue.CONFLICT:
            # 충돌이면 값은 비우고 후보를 둘 이상 남긴다
            if self.value is not None:
                raise ValueError("conflict면 value는 null")
            if len(self.candidates) < 2:
                raise ValueError("conflict면 candidates가 2개 이상")
        elif self.candidates:
            raise ValueError("candidates는 conflict일 때만")
        return self


# 나쁜 순서: 앞일수록 나쁘다
_WORST_ORDER = [
    StatusValue.CONFLICT,
    StatusValue.UNVERIFIED,
    StatusValue.NOT_FOUND_IN_SCOPE,
    StatusValue.CONFIRMED,
]


def worst_status(statuses: list[Status], checked_summary: str) -> Status:
    """칸들의 status 중 가장 나쁜 것을 결과 전체 status로 모은다.

    같은 등급이 여럿이면 앞 칸의 reason·searched_scope를 쓴다.
    모두 confirmed면 checked는 checked_summary.
    """
    if not statuses:
        logger.warning("worst_status: 모을 status가 없음 (빈 목록) -> unverified(not_extracted)")
        return Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
    for level in _WORST_ORDER:
        for s in statuses:  # 앞 칸부터 보므로 같은 등급이면 앞 칸이 이긴다
            if s.value == level:
                if level == StatusValue.CONFIRMED:
                    return Status(value=level, checked=checked_summary)
                return s.model_copy()
    raise AssertionError("도달할 수 없음")  # pragma: no cover
