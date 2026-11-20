"""Drafts(⑤): 의견서 초안과 보정 청구항 초안. 모양의 기준은 docs/data-model.md 4절 ⑤ 줄.

AI 원문(ai_text)은 늘 남기고, 사람이 고친 글은 human_text에 따로 둔다 (origin=human_edited).
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator

from patent_ai.core.schemas.common import Evidence, Origin, ResultBase


class OpinionKey(StrEnum):
    """의견서 칸. 선언 순서가 의견서 순서다."""

    CASE_INFO = "case_info"  # 사건 정보
    POINTS = "points"  # 지적 요지
    RESPONSE = "response"  # 대응과 근거
    AMENDMENT = "amendment"  # 보정 설명
    CLOSING = "closing"  # 마무리


_OPINION_ORDER = list(OpinionKey)


def _check_human_edit(human_text: str | None, origin: Origin) -> None:
    """사람이 고친 글이 있음 <=> origin human_edited. 고친 글은 공백만일 수 없다."""
    if origin not in (Origin.AI_GENERATED, Origin.HUMAN_EDITED):
        raise ValueError("origin은 ai_generated·human_edited만")
    if (human_text is not None) != (origin == Origin.HUMAN_EDITED):
        raise ValueError("human_text는 origin이 human_edited일 때만, 그리고 그때는 꼭 채운다")
    if human_text is not None and not human_text.strip():
        raise ValueError("human_text가 비어 있음")


class OpinionSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: OpinionKey
    title: str
    ai_text: str  # AI 원문 (비우지 못함)
    human_text: str | None = None
    origin: Origin = Origin.AI_GENERATED

    @model_validator(mode="after")
    def _AI_원문은_남긴다(self) -> OpinionSection:
        if not self.ai_text.strip():
            raise ValueError("ai_text가 비어 있음")
        _check_human_edit(self.human_text, self.origin)
        return self


class AmendedClaim(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: int
    unit_id: str
    before: str  # OA 당시 청구항
    ai_text: str | None  # 보정 초안 AI 원문. 보류면 null
    human_text: str | None = None
    origin: Origin = Origin.AI_GENERATED
    spec_basis: list[Evidence]  # 최초 명세서 근거 위치
    held_reason: str | None  # 보류 이유 (확신 낮은 묶음: 방향을 골라 주세요)

    @model_validator(mode="after")
    def _보류와_AI_원문(self) -> AmendedClaim:
        held = self.ai_text is None
        if held != (self.held_reason is not None):
            raise ValueError("held_reason은 ai_text가 null(보류)일 때만, 그리고 그때는 꼭 채운다")
        if self.held_reason is not None and not self.held_reason.strip():
            raise ValueError("held_reason이 비어 있음")
        if self.ai_text is not None and not self.ai_text.strip():
            raise ValueError("ai_text가 비어 있음")
        if held and self.human_text is not None:
            raise ValueError("보류된 청구항은 고칠 AI 원문이 없어 human_text를 못 둠")
        _check_human_edit(self.human_text, self.origin)
        return self


class BasedOn(BaseModel):
    """이 초안을 만들 때 쓴 선택 (묶음마다 후보 하나)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_id: str
    candidate_id: str


class Drafts(ResultBase):
    draft_id: str
    based_on: list[BasedOn]
    opinion: list[OpinionSection]
    claims: list[AmendedClaim]

    @model_validator(mode="after")
    def _검사(self) -> Drafts:
        keys = [s.key for s in self.opinion]
        if len(set(keys)) != len(keys):
            raise ValueError("opinion key에 중복이 있음")
        if keys != [k for k in _OPINION_ORDER if k in keys]:
            raise ValueError("opinion은 case_info·points·response·amendment·closing 순서")
        units = [b.unit_id for b in self.based_on]
        if len(set(units)) != len(units):
            raise ValueError("based_on의 unit_id에 중복이 있음")
        return self
