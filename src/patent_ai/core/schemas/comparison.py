"""ComparisonTable(③)·ClarityReview: F3가 내는 대비표와 명확성 문구 검토.

기준은 이 코드, 설명은 docs/data-model.md 4절 ③ 줄. 결과 status는 rows의 가장 나쁜 값과 같아야 한다.
인용문헌 위치(식별번호·도면 번호)는 공통 칸 evidence[].location에 둔다.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from patent_ai.core.schemas.common import (
    Evidence,
    Flag,
    ResultBase,
    Status,
    StatusValue,
    worst_status,
)
from patent_ai.core.schemas.judgment_unit import UNIT_ID_FORM, UnitId
from patent_ai.core.schemas.oa_result import RejectionKind

ALL_ROWS_CHECKED = "모든 줄 원문 대조"  # 모두 confirmed일 때 결과 status의 checked


class Judgment(StrEnum):
    DISCLOSED = "disclosed"  # 개시됨
    DIFFERENCE_CANDIDATE = "difference_candidate"  # 차이 후보
    UNCLEAR = "unclear"  # 불명


class ParagraphSource(StrEnum):
    EXAMINER = "examiner"  # 심사관 지정
    AI_FOUND = "ai_found"  # AI가 새로 찾음


class NoveltyVerdict(StrEnum):
    NO_DIFFERENCE = "no_difference"
    SUBSTANTIALLY_SAME_CANDIDATE = "substantially_same_candidate"
    DIFFERENT = "different"


class ComparisonRow(ResultBase):
    claim: int = Field(ge=1)  # OA 시점 청구항 번호 (정답·채점이 청구항마다)
    element: str  # 청구항 구성요소 문구
    element_location: str  # 청구항 안 위치
    citation: str  # 인용문헌 라벨 D1…
    judgment: Judgment
    paragraph_source: ParagraphSource
    why_retrieved: str | None = None  # AI가 새로 찾은 문단만

    @model_validator(mode="after")
    def _왜_가져왔나는_AI가_찾은_문단만(self) -> ComparisonRow:
        ai_found = self.paragraph_source == ParagraphSource.AI_FOUND
        has_reason = self.why_retrieved is not None and bool(self.why_retrieved.strip())
        if ai_found != (self.why_retrieved is not None):
            raise ValueError("why_retrieved는 ai_found일 때만, 그리고 그때는 꼭 채운다")
        if ai_found and not has_reason:
            raise ValueError("why_retrieved가 비어 있음")
        # 개시됨을 확인됨으로 두려면 인용문헌 원문 위치가 있어야 한다
        # (차이 후보·불명은 그 구성이 인용문헌에 없다는 뜻이라 위치가 없을 수 있다)
        if (
            self.judgment == Judgment.DISCLOSED
            and self.status.value == StatusValue.CONFIRMED
            and not self.evidence
        ):
            raise ValueError("disclosed이고 confirmed인 줄은 evidence가 하나 이상 필요")
        return self


class ComparedCitation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    number: str
    compared: bool  # false면 대비 안 함 (지원 안 하는 나라 등)
    skipped_reason: str | None = None
    skipped_status: Status | None = None

    @model_validator(mode="after")
    def _대비하면_이유가_없고_안_하면_이유가_있다(self) -> ComparedCitation:
        if self.compared:
            if self.skipped_reason is not None or self.skipped_status is not None:
                raise ValueError("compared면 skipped_reason·skipped_status는 null")
        elif self.skipped_reason is None or self.skipped_status is None:
            raise ValueError("compared=false면 skipped_reason·skipped_status를 채운다")
        return self


class InventiveSummary(BaseModel):
    """진보성 요약: 차이점 → 결합 → 효과 후보 순."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["inventive_step"]
    differences: list[str]
    combination: str
    effect_candidates: list[str]


class NoveltySummary(BaseModel):
    """신규성 요약: 인용 하나와만."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["novelty"]
    citation: str
    verdict: NoveltyVerdict
    reason: str


def summarize_table_status(rows: list[ComparisonRow]) -> Status:
    """rows의 status 중 가장 나쁜 것을 대비표 status로 모은다 (만드는 쪽이 쓴다)."""
    return worst_status([r.status for r in rows], ALL_ROWS_CHECKED)


class ComparisonTable(ResultBase):
    unit_id: UnitId
    rejection_kind: RejectionKind
    citations: list[ComparedCitation]
    rows: list[ComparisonRow]
    summary: InventiveSummary | NoveltySummary = Field(discriminator="kind")

    @model_validator(mode="after")
    def _검사(self) -> ComparisonTable:
        kind = self.rejection_kind
        if kind not in (RejectionKind.NOVELTY, RejectionKind.INVENTIVE_STEP):
            raise ValueError("대비표는 novelty·inventive_step만 (명확성은 ClarityReview)")
        if self.summary.kind != kind.value:
            raise ValueError("summary.kind가 rejection_kind와 다름")
        labels = [c.label for c in self.citations]
        if len(set(labels)) != len(labels):
            raise ValueError("인용 라벨에 중복이 있음")
        compared = {c.label for c in self.citations if c.compared}
        for row in self.rows:
            # 대비하지 않은 인용문헌으로는 줄을 만들 수 없다
            if row.citation not in compared:
                raise ValueError(f"rows의 인용 {row.citation}는 compared=true인 인용이 아님")
        if kind == RejectionKind.NOVELTY:
            # 신규성은 인용 하나와만 비교한다
            if len(compared) != 1:
                raise ValueError("신규성은 compared=true 인용이 정확히 하나")
            if isinstance(self.summary, NoveltySummary) and self.summary.citation not in compared:
                raise ValueError("NoveltySummary.citation이 대비한 인용과 다름")
        # 지원 안 하는 나라는 status를 나쁘게 하지 않고 flags로만 알린다
        if any(not c.compared for c in self.citations) and (
            Flag.NEEDS_HUMAN_REVIEW not in self.flags
        ):
            raise ValueError("compared=false 인용이 있으면 flags에 needs_human_review가 필요")
        expected = summarize_table_status(self.rows)
        if self.status.value != expected.value:
            raise ValueError(f"status {self.status.value}가 rows를 모은 값 {expected.value}와 다름")
        return self


class ClarityReview(ResultBase):
    """명확성 문구 검토: 청구항 하나에서 짚은 문구와 최초 명세서의 정의."""

    unit_id: UnitId
    claim: int
    term: str  # 짚은 문구
    claim_location: str  # 청구항 안 위치
    spec_definition: Evidence | None = None  # 최초 명세서의 정의 위치 (location에 `[0016]`)
    note: str

    @model_validator(mode="after")
    def _검사(self) -> ClarityReview:
        if not self.term.strip():
            raise ValueError("term이 비어 있음")
        if not self.note.strip():
            raise ValueError("note가 비어 있음")
        # 실제 근거는 spec_definition 한 곳: 물려받은 evidence 칸은 쓰지 않는다
        if self.evidence:
            raise ValueError("evidence는 비워 둔다 (근거는 spec_definition)")
        if self.status.value == StatusValue.CONFIRMED and self.spec_definition is None:
            raise ValueError("confirmed면 spec_definition(명세서 정의 위치)이 필요")
        # claim은 unit_id의 c번호(대표 청구항)와 같아야 한다
        m = UNIT_ID_FORM.fullmatch(self.unit_id)
        if m is None or int(m["claim"]) != self.claim:
            raise ValueError("claim이 unit_id의 c번호와 다르거나 unit_id 꼴이 아님")
        return self
