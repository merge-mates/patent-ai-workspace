"""DirectionCandidates(⑤): F4가 내는 대응 방향 후보. 기준은 data-model.md 4절 ⑤ 줄과 ADR 0001.

AI는 방향을 확정하지 않는다. 순위·이유·확신도까지만 내고, 확신이 낮으면 순위 없이
"직접 판단 필요"로 둔다. 고르는 것은 사람이다 (selection.origin으로 AI 기본값과 사람 선택을 구분).
"""

import logging
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator

from patent_ai.core.schemas.common import (
    ExtractedValue,
    Flag,
    Origin,
    ResultBase,
    Status,
    StatusValue,
    UnverifiedReason,
    worst_status,
)
from patent_ai.core.schemas.oa_result import RejectionKind

logger = logging.getLogger(__name__)

ALL_DIRECTIONS_CHECKED = "모든 후보·보정 제한 확인"  # 모두 confirmed일 때 결과 status의 checked


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"  # 낮음 = 직접 판단 필요


class CoarseDirection(StrEnum):
    ARGUE_ONLY = "argue_only"  # 반박만
    AMEND_AND_ARGUE = "amend_and_argue"  # 보정 + 반박
    AMEND_ONLY = "amend_only"  # 보정만


class AmendmentKind(StrEnum):
    UNCHANGED = "unchanged"
    LIMIT = "limit"  # 한정
    ADD = "add"  # 구성 부가
    DELETE = "delete"
    CORRECT_ERROR = "correct_error"  # 오기 정정
    CLARIFY = "clarify"  # 명확화


class AddedSource(StrEnum):
    """부가한 구성이 어디서 왔나."""

    OTHER_DEPENDENT = "other_dependent"  # 다른 종속항
    SPEC = "spec"  # 명세서
    OTHER = "other"


class AmendmentLimit(StrEnum):
    INITIAL = "initial"  # 최초 거절이유통지 (보정 제한 느슨)
    FINAL = "final"  # 최후 거절이유통지 (보정 제한 엄격)


class RebuttalType(StrEnum):
    DIFFERENCE = "difference"  # 차이점
    NO_MOTIVATION = "no_motivation"  # 결합 동기 없음
    COMBINATION_DIFFICULTY = "combination_difficulty"  # 결합 곤란
    REMARKABLE_EFFECT = "remarkable_effect"  # 현저한 효과
    HINDSIGHT = "hindsight"  # 사후적 고찰
    NOT_SUBSTANTIALLY_SAME = "not_substantially_same"  # 실질적 동일 아님
    GRACE_PERIOD = "grace_period"  # 공지예외
    OBVIOUS_ERROR = "obvious_error"  # 명백한 오기
    CLEAR_FROM_DESCRIPTION = "clear_from_description"  # 설명으로 명확
    OTHER = "other"


R = RebuttalType
# 거절이유 종류별로 쓸 수 있는 반박 논리 유형 (other 종류는 반박 유형이 없다)
REBUTTAL_TYPES_BY_KIND: dict[RejectionKind, frozenset[RebuttalType]] = {
    RejectionKind.INVENTIVE_STEP: frozenset(
        {
            R.DIFFERENCE,
            R.NO_MOTIVATION,
            R.COMBINATION_DIFFICULTY,
            R.REMARKABLE_EFFECT,
            R.HINDSIGHT,
            R.OTHER,
        }
    ),
    RejectionKind.NOVELTY: frozenset(
        {R.DIFFERENCE, R.NOT_SUBSTANTIALLY_SAME, R.GRACE_PERIOD, R.OTHER}
    ),
    RejectionKind.CLARITY: frozenset({R.OBVIOUS_ERROR, R.CLEAR_FROM_DESCRIPTION, R.OTHER}),
}


class Rebuttal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rejection_kind: RejectionKind
    type: RebuttalType
    summary: str

    @model_validator(mode="after")
    def _유형은_거절이유_종류에_맞아야_한다(self) -> Rebuttal:
        allowed = REBUTTAL_TYPES_BY_KIND.get(self.rejection_kind)
        if allowed is None:
            raise ValueError(f"{self.rejection_kind.value} 종류에는 반박 유형이 없음")
        if self.type not in allowed:
            raise ValueError(
                f"반박 유형 {self.type.value}는 {self.rejection_kind.value}에 맞지 않음"
            )
        if not self.summary.strip():
            raise ValueError("summary가 비어 있음")
        return self


class AmendmentCore(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: int
    kind: AmendmentKind
    source: AddedSource | None = None  # 부가한 구성의 출처 (kind=add일 때만)

    @model_validator(mode="after")
    def _출처는_구성을_부가할_때만(self) -> AmendmentCore:
        if (self.kind == AmendmentKind.ADD) != (self.source is not None):
            raise ValueError("source는 kind=add일 때만, 그리고 add면 꼭 채운다")
        return self


class RejectionResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rejection: int
    response: str

    @model_validator(mode="after")
    def _대응은_비지_않아야_한다(self) -> RejectionResponse:
        if not self.response.strip():
            raise ValueError("response가 비어 있음")
        return self


class DirectionCandidate(ResultBase):
    candidate_id: str
    rank: int | None  # 1부터. 확신 낮음이면 null (순위 없음)
    coarse: CoarseDirection
    name: str
    confidence: Confidence
    reason: str  # 짧은 이유 한 줄 (늘 보임)
    checks: list[str]
    per_rejection: list[RejectionResponse]
    amendment_core: list[AmendmentCore]
    rebuttal: Rebuttal | None

    @model_validator(mode="after")
    def _검사(self) -> DirectionCandidate:
        if not self.reason.strip():
            raise ValueError("reason이 비어 있음")
        low = self.confidence == Confidence.LOW
        # 확신 낮음 <=> 순위 없음. 낮으면 "직접 판단 필요" 표시
        if low != (self.rank is None):
            raise ValueError("confidence가 low일 때만, 그리고 low면 꼭 rank는 null")
        if self.rank is not None and self.rank < 1:
            raise ValueError("rank는 1부터")
        if low and Flag.NEEDS_HUMAN_JUDGMENT not in self.flags:
            raise ValueError("confidence가 low면 flags에 needs_human_judgment가 필요")
        # 방향 종류에 맞는 보정·반박 짜임
        amended = [a for a in self.amendment_core if a.kind != AmendmentKind.UNCHANGED]
        if self.coarse == CoarseDirection.ARGUE_ONLY:
            if amended:
                raise ValueError("argue_only는 보정이 모두 unchanged (또는 없음)")
            if self.rebuttal is None:
                raise ValueError("argue_only는 rebuttal이 필요")
        else:
            if not amended:
                raise ValueError(f"{self.coarse.value}는 unchanged가 아닌 보정이 하나 이상 필요")
            if self.coarse == CoarseDirection.AMEND_AND_ARGUE and self.rebuttal is None:
                raise ValueError("amend_and_argue는 rebuttal이 필요")
            if self.coarse == CoarseDirection.AMEND_ONLY and self.rebuttal is not None:
                raise ValueError("amend_only는 rebuttal이 null")
        return self


class DirectionSelection(BaseModel):
    """묶음에서 고른 후보. AI 기본값과 사람 선택을 origin으로 구분한다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    origin: Origin

    @model_validator(mode="after")
    def _선택의_출처만(self) -> DirectionSelection:
        if self.origin not in (Origin.AI_DEFAULT, Origin.HUMAN_SELECTED):
            raise ValueError("selection.origin은 ai_default·human_selected만")
        return self


def summarize_direction_status(
    candidates: list[DirectionCandidate], amendment_limit: ExtractedValue[AmendmentLimit]
) -> Status:
    """후보들과 보정 제한의 status 중 가장 나쁜 것을 결과 status로 모은다 (만드는 쪽이 쓴다)."""
    if not candidates:
        # 후보가 하나도 없으면 보정 제한 상태와 상관없이 확인되지 않음
        logger.warning("summarize_direction_status: 후보가 없음 -> unverified(not_extracted)")
        return Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
    statuses = [c.status for c in candidates] + [amendment_limit.status]
    return worst_status(statuses, ALL_DIRECTIONS_CHECKED)


class DirectionCandidates(ResultBase):
    unit_id: str
    candidates: list[DirectionCandidate]
    selection: DirectionSelection | None
    amendment_limit: ExtractedValue[AmendmentLimit]

    @model_validator(mode="after")
    def _검사(self) -> DirectionCandidates:
        if not self.candidates and self.status.value != StatusValue.UNVERIFIED:
            raise ValueError("후보가 0개면 status는 unverified여야 함")
        ids = [c.candidate_id for c in self.candidates]
        if len(set(ids)) != len(ids):
            raise ValueError("candidate_id에 중복이 있음")
        # 순위는 1..n 연속, 중복 없음
        ranks = sorted(c.rank for c in self.candidates if c.rank is not None)
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("rank는 1부터 빠짐·중복 없이 이어져야 함")
        sel = self.selection
        if sel is not None:
            chosen = next((c for c in self.candidates if c.candidate_id == sel.candidate_id), None)
            if chosen is None:
                raise ValueError("selection.candidate_id가 후보 안에 없음")
            # AI 기본값은 1등만 가리킬 수 있다
            if sel.origin == Origin.AI_DEFAULT and chosen.rank != 1:
                raise ValueError("ai_default 선택은 rank 1 후보를 가리켜야 함")
        if not ranks:
            # 순위 있는 후보가 없는 묶음 = 확신 낮은 묶음: 미리 고르지 않고 직접 판단
            # (ai_default는 위에서 rank 1이 아니라며 이미 거부됨)
            if Flag.NEEDS_HUMAN_JUDGMENT not in self.flags:
                raise ValueError("순위 있는 후보가 없으면 flags에 needs_human_judgment가 필요")
        # 보정 제한을 모르면 확인됨일 수 없다
        if (
            self.amendment_limit.value is None
            and self.amendment_limit.status.value == StatusValue.CONFIRMED
        ):
            raise ValueError("amendment_limit.value가 null이면 status는 confirmed일 수 없음")
        expected = summarize_direction_status(self.candidates, self.amendment_limit)
        if self.status.value != expected.value:
            raise ValueError(f"status {self.status.value}가 안쪽을 모은 값 {expected.value}와 다름")
        return self
