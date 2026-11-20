"""LegalEvidenceBundle(④): F2가 내는 법률 근거 묶음.

기준은 이 코드, 설명은 docs/data-model.md 4절 ④ 줄. 결과 status는 안쪽 가장 나쁜 값과 같아야 한다.
법령·심사기준은 판본(시행일·개정일)을 모르면 confirmed가 될 수 없다.
"이 사건에 적용된다"는 칸은 두지 않는다 (사건 적용일로 자동 확정하지 않는다, 사람이 판단).
근거 위치는 공통 Evidence를 쓴다 (edition=판본, location=원문 위치, raw_text=발췌).
"""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from patent_ai.core.schemas.common import (
    Evidence,
    ResultBase,
    Status,
    StatusValue,
    worst_status,
)
from patent_ai.core.schemas.judgment_unit import UnitId

ALL_SOURCES_CHECKED = "모든 근거 원문 대조"  # 주장 안 근거가 모두 confirmed일 때 checked
ALL_CLAIMS_CHECKED = "모든 주장 근거 확인"  # 묶음 안 주장이 모두 confirmed일 때 checked


class LegalSourceKind(StrEnum):
    STATUTE = "statute"  # 법령
    EXAM_GUIDELINE = "exam_guideline"  # 심사기준
    PRECEDENT = "precedent"  # 판례
    TRIAL_DECISION = "trial_decision"  # 심결례


class TextKind(StrEnum):
    FULL = "full"  # 전문
    SUMMARY = "summary"  # 요지


class Speaker(StrEnum):
    COURT = "court"  # 법원 판단
    PARTY = "party"  # 당사자 주장


# 판본(시행일·개정일)이 있는 근거 종류
_VERSIONED = (LegalSourceKind.STATUTE, LegalSourceKind.EXAM_GUIDELINE)


class LegalSource(BaseModel):
    """법률 근거 하나: 조문·판결·심결·심사기준 절."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_kind: LegalSourceKind
    identifier: str  # 조문·판결 번호·심결 번호·심사기준 절
    text_kind: TextKind
    speaker: Speaker | None = None  # 판례·심결례에서만
    evidence: Evidence  # raw_text=발췌, edition=판본, location=원문 위치
    status: Status

    @model_validator(mode="after")
    def _검사(self) -> LegalSource:
        if not self.identifier.strip():
            raise ValueError("identifier가 비어 있음")
        if self.source_kind in _VERSIONED:
            edition = self.evidence.edition
            # 판본을 모르는 법령·심사기준은 확인됨으로 둘 수 없다
            if (edition is None or not edition.strip()) and (
                self.status.value == StatusValue.CONFIRMED
            ):
                raise ValueError("판본(edition) 없는 법령·심사기준은 confirmed 불가")
            if self.speaker is not None:
                raise ValueError("법령·심사기준은 speaker가 null")
        return self


def summarize_claim_status(sources: list[LegalSource]) -> Status:
    """근거들의 status 중 가장 나쁜 것을 주장 status로 모은다 (만드는 쪽이 쓴다)."""
    return worst_status([s.status for s in sources], ALL_SOURCES_CHECKED)


# 비어 있는 목록(근거 0개 주장, 주장 0개 묶음)에 둘 수 있는 status.
# F2는 찾아본 범위에 결과가 없으면 not_found_in_scope, 못 찾은 이유가 따로 있으면 unverified로 둔다.
_EMPTY_OK = {StatusValue.UNVERIFIED, StatusValue.NOT_FOUND_IN_SCOPE}


def _빈_목록_status_검사(status: Status, what: str) -> None:
    if status.value not in _EMPTY_OK:
        raise ValueError(f"{what}가 비어 있으면 status는 unverified 또는 not_found_in_scope")


class LegalClaim(ResultBase):
    no: int = Field(ge=1)
    text: str  # 주장 문장
    sources: list[LegalSource]

    @model_validator(mode="after")
    def _검사(self) -> LegalClaim:
        if not self.text.strip():
            raise ValueError("text가 비어 있음")
        if not self.sources:
            # 근거 0개는 모을 값이 없다: 확인됨·충돌만 막는다
            _빈_목록_status_검사(self.status, "sources")
            return self
        expected = summarize_claim_status(self.sources)
        if self.status.value != expected.value:
            raise ValueError(f"status {self.status.value}가 근거를 모은 값 {expected.value}와 다름")
        return self


def summarize_bundle_status(claims: list[LegalClaim]) -> Status:
    """주장들의 status 중 가장 나쁜 것을 묶음 status로 모은다 (만드는 쪽이 쓴다)."""
    return worst_status([c.status for c in claims], ALL_CLAIMS_CHECKED)


class LegalEvidenceBundle(ResultBase):
    bundle_id: str
    unit_id: UnitId | None = None  # OA 흐름이면 판단 단위, 법률 질문이면 null
    question: str
    as_of: date | None = None  # 사용자가 정한 시점, 없으면 현행
    checked_on: date  # 확인 기준일
    claims: list[LegalClaim]
    further_review: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _검사(self) -> LegalEvidenceBundle:
        nos = [c.no for c in self.claims]
        if len(set(nos)) != len(nos):
            raise ValueError("claims의 no에 중복이 있음")
        if not self.claims:
            _빈_목록_status_검사(self.status, "claims")
            return self
        expected = summarize_bundle_status(self.claims)
        if self.status.value != expected.value:
            raise ValueError(f"status {self.status.value}가 주장을 모은 값 {expected.value}와 다름")
        return self
