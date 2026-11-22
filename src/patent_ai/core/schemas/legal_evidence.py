"""LegalEvidenceBundle(④): F2가 내는 법률 근거 묶음.

기준은 이 코드, 설명은 docs/data-model.md 4절 ④ 줄. 결과 status는 안쪽 가장 나쁜 값과 같아야 한다.
법령·심사기준은 판본(시행일·개정일)을 모르면 confirmed가 될 수 없다.
"이 사건에 적용된다"는 칸은 두지 않는다 (사건 적용일로 자동 확정하지 않는다, 사람이 판단).
질문·검토·더 볼 조각·검색 기록 칸은 F2 design 3-2절 제안에서 왔다.
칸 이름·모양은 이 코드가 기준이다 (F2 design 3-2절은 #29에서 이 코드에 맞춘다).
근거 위치는 공통 Evidence를 쓴다 (edition=판본, location=원문 위치, raw_text=발췌).
"""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from patent_ai.core.schemas.common import (
    Evidence,
    Flag,
    ResultBase,
    Status,
    StatusValue,
    worst_status,
)
from patent_ai.core.schemas.judgment_unit import UnitId

ALL_SOURCES_CHECKED = "모든 근거 원문 대조"  # 주장 안 근거가 모두 confirmed일 때 checked
ALL_CLAIMS_CHECKED = "모든 주장 근거 확인"  # 묶음 안 주장이 모두 confirmed일 때 checked


class LegalSourceKind(StrEnum):
    """자료 종류. 값은 #24 색인의 source_kind와 같다."""

    STATUTE = "statute"  # 법령
    GUIDELINE = "guideline"  # 심사기준
    PRECEDENT = "precedent"  # 판례
    TRIAL = "trial"  # 심결


class TextKind(StrEnum):
    FULL = "full"  # 전문
    SUMMARY = "summary"  # 요지


class Speaker(StrEnum):
    COURT = "court"  # 법원 판단
    PARTY = "party"  # 당사자 주장
    UNKNOWN = "unknown"  # 누구 말인지 모름 (직접 검토 필요)


class QuestionSource(StrEnum):
    OA_REJECTION = "oa_rejection"  # OA 거절이유에서 나온 질문
    USER_QUESTION = "user_question"  # 사용자가 직접 한 질문


class AsOfSource(StrEnum):
    USER_TEXT = "user_text"  # 질문 글에서 읽음
    USER_CONDITION = "user_condition"  # 사용자가 조건으로 정함
    OA_DISPATCH_DATE = "oa_dispatch_date"  # OA 발송일
    NONE = "none"  # 없음 (현행)


class ReviewVerdict(StrEnum):
    SUPPORTED = "supported"  # 근거가 뒷받침
    PARTIAL = "partial"  # 일부만
    NOT_SUPPORTED = "not_supported"  # 뒷받침 못 함
    UNDETERMINED = "undetermined"  # 판정 못 함


class FurtherReviewWhy(StrEnum):
    OPPOSITE_HOLDING = "opposite_holding"  # 반대 취지 판례
    EDITION_UNKNOWN = "edition_unknown"  # 판본을 모름
    OTHER_EDITION = "other_edition"  # 다른 판본
    EDITION_OUT_OF_SCOPE = "edition_out_of_scope"  # 기준일 밖 판본
    NOT_USED_CANDIDATE = "not_used_candidate"  # 후보였지만 쓰지 않음


# 판본(시행일·개정일)이 있는 근거 종류
_VERSIONED = (LegalSourceKind.STATUTE, LegalSourceKind.GUIDELINE)


class LegalQuestion(BaseModel):
    """F2가 받은 질문 하나. oa_id·rejection은 묶음 맨 위 칸에 둔다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    source: QuestionSource
    as_of: date | None = None  # 검색 기준일, 없으면 현행
    as_of_source: AsOfSource
    source_kinds: list[LegalSourceKind]  # 어디를 찾을지 (비지 않음, 중복 없음)
    article_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _검사(self) -> LegalQuestion:
        if not self.text.strip():
            raise ValueError("text가 비어 있음")
        if not self.source_kinds:
            raise ValueError("source_kinds가 비어 있음")
        if len(set(self.source_kinds)) != len(self.source_kinds):
            raise ValueError("source_kinds에 중복이 있음")
        # 기준일과 그 출처는 함께 있거나 함께 없다
        if (self.as_of is None) != (self.as_of_source == AsOfSource.NONE):
            raise ValueError("as_of가 없을 때만, 그리고 없으면 꼭 as_of_source는 none")
        return self


class Review(BaseModel):
    """주장이 근거로 뒷받침되는지 검토한 결과 (AI 판정, 사람이 확인)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: ReviewVerdict
    reason: str

    @model_validator(mode="after")
    def _검사(self) -> Review:
        if not self.reason.strip():
            raise ValueError("reason이 비어 있음")
        return self


class LegalSource(BaseModel):
    """법률 근거 하나: 조문·판결·심결·심사기준 절."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_kind: LegalSourceKind
    identifier: str  # 조문·판결 번호·심결 번호·심사기준 절
    evidence: Evidence  # raw_text=발췌, edition=판본, location=원문 위치
    status: Status
    text_kind: TextKind | None = None  # 판례·심결만
    speaker: Speaker | None = None  # 판례·심결만
    decided_on: date | None = None  # 판례 선고일·심결 심결일, 모르면 null
    court: str | None = None

    @model_validator(mode="after")
    def _검사(self) -> LegalSource:
        if not self.identifier.strip():
            raise ValueError("identifier가 비어 있음")
        # 확인됨이면 원문 발췌가 있어야 한다 (법령·심사기준·판례·심결 모두)
        if (
            self.status.value == StatusValue.CONFIRMED
            and not (self.evidence.raw_text or "").strip()
        ):
            raise ValueError("confirmed 근거는 evidence.raw_text(원문 발췌)가 비지 않아야 함")
        if self.source_kind in _VERSIONED:
            edition = self.evidence.edition
            # 판본을 모르는 법령·심사기준은 확인됨으로 둘 수 없다
            if (edition is None or not edition.strip()) and (
                self.status.value == StatusValue.CONFIRMED
            ):
                raise ValueError("판본(edition) 없는 법령·심사기준은 confirmed 불가")
            if (
                self.text_kind is not None
                or self.speaker is not None
                or self.decided_on is not None
                or self.court is not None
            ):
                raise ValueError("법령·심사기준은 text_kind·speaker·decided_on·court가 null")
        elif self.text_kind is None or self.speaker is None:
            raise ValueError("판례·심결은 text_kind와 speaker가 필수")
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
    review: Review | None = None

    @model_validator(mode="after")
    def _검사(self) -> LegalClaim:
        if not self.text.strip():
            raise ValueError("text가 비어 있음")
        # 실제 근거는 sources[].evidence 한 곳: 물려받은 evidence 칸은 쓰지 않는다
        if self.evidence:
            raise ValueError("evidence는 비워 둔다 (근거는 sources[].evidence)")
        # 검토하지 않은 주장이 조용히 confirmed로 보이지 않게 한다
        if self.sources and self.review is None and Flag.NEEDS_HUMAN_REVIEW not in self.flags:
            raise ValueError("근거가 있는데 review가 없으면 flags에 needs_human_review가 필요")
        # 사람이 꼭 봐야 하는 경우는 flags로 드러낸다
        if (
            self.review is not None and self.review.verdict != ReviewVerdict.SUPPORTED
        ) and Flag.NEEDS_HUMAN_REVIEW not in self.flags:
            raise ValueError("review가 supported가 아니면 flags에 needs_human_review가 필요")
        if (
            any(s.speaker == Speaker.UNKNOWN for s in self.sources)
            and Flag.NEEDS_HUMAN_REVIEW not in self.flags
        ):
            raise ValueError("speaker가 unknown인 근거가 있으면 flags에 needs_human_review가 필요")
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


class FurtherReview(BaseModel):
    """주장에 쓰지 않았지만 사람이 더 볼 만한 색인 조각."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    why: FurtherReviewWhy
    note: str | None = None
    index_version: str | None = None  # 조각이 속한 색인 판

    @model_validator(mode="after")
    def _검사(self) -> FurtherReview:
        if not self.chunk_id.strip():
            raise ValueError("chunk_id가 비어 있음")
        return self


class SearchLogEntry(BaseModel):
    """자료 종류 하나를 어떻게 찾았나 (못 찾음 ≠ 없음을 가르는 기록)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_kind: LegalSourceKind
    index_version: str | None = None
    as_of: date | None = None
    queries: int = Field(ge=0)
    hits: int = Field(ge=0)
    skipped_unverified_edition: int = Field(default=0, ge=0)  # 판본을 몰라 뺀 조각 수
    skipped_unknown_date: int = Field(default=0, ge=0)  # 날짜를 몰라 뺀 조각 수
    # 이 자료 유형을 찾은 결과 상태 (None = 기록하지 않음). 묶음이 확인됨이어도 안 본 유형이
    # 무엇이고 왜인지(예: 심사기준 unverified(body_missing)) 화면·채점이 이 칸을 읽는다 (#222 리뷰)
    status: Status | None = None


class LegalEvidenceBundle(ResultBase):
    bundle_id: str
    unit_id: UnitId | None = None  # OA 흐름이면 판단 단위, 법률 질문이면 null
    oa_id: str | None = None  # DB 거르기 칸: oa_rejection 질문일 때만
    rejection: int | None = Field(default=None, ge=1)  # 거절이유 번호, oa_rejection일 때만
    question: LegalQuestion
    checked_on: date  # 확인 기준일
    clarifications: list[str] = Field(default_factory=list)  # 시점이 부딪힐 때 확인한 글
    claims: list[LegalClaim]
    further_review: list[FurtherReview] = Field(default_factory=list)
    search_log: list[SearchLogEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _검사(self) -> LegalEvidenceBundle:
        from_oa = self.question.source == QuestionSource.OA_REJECTION
        # OA 거절이유 질문이면 oa_id·rejection이 둘 다, 직접 질문이면 둘 다 null
        if from_oa != (self.oa_id is not None and self.rejection is not None):
            raise ValueError("oa_rejection이면 oa_id·rejection 둘 다 있고, 아니면 둘 다 null")
        if not from_oa and (self.oa_id is not None or self.rejection is not None):
            raise ValueError("user_question이면 oa_id·rejection은 null")
        if self.unit_id is not None:
            if not from_oa or self.oa_id is None or not self.unit_id.startswith(self.oa_id + ":"):
                raise ValueError("unit_id는 oa_rejection 질문이고 oa_id + ':'로 시작해야 함")
        nos = [c.no for c in self.claims]
        if len(set(nos)) != len(nos):
            raise ValueError("claims의 no에 중복이 있음")
        if not self.claims:
            _빈_목록_status_검사(self.status, "claims")
            # 못 찾음 != 없음: 판본·날짜를 몰라 뺀 조각이 있으면 "없음"이 아니라 unverified
            skipped = sum(
                e.skipped_unverified_edition + e.skipped_unknown_date for e in self.search_log
            )
            if skipped > 0 and self.status.value == StatusValue.NOT_FOUND_IN_SCOPE:
                raise ValueError(
                    "skipped 조각이 있으면 not_found_in_scope 불가 (unverified edition_unknown)"
                )
            return self
        expected = summarize_bundle_status(self.claims)
        if self.status.value != expected.value:
            raise ValueError(f"status {self.status.value}가 주장을 모은 값 {expected.value}와 다름")
        return self
