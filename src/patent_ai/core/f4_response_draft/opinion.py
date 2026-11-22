"""의견서 초안 단계: 방향을 고른 묶음마다 모델을 한 번 불러 의견서 칸을 만든다.

글을 쓰는 것은 모델(프롬프트)이 한다. 코드는 확인만 한다:
- 고른 후보 하나만 프롬프트에 준다 (고르지 않은 방향의 문장이 초안에 섞이지 않게)
- 고른 후보가 없는 묶음(확신 낮음)은 모델을 부르지 않고 보류한다 (그 묶음만)
- 칸이 비었거나 보정 설명 유무가 고른 방향과 어긋나면 출력 검사 실패 (한 번 다시 부름)
- status는 고른 후보와 법률 근거 묶음에서 전파한다 (법률 근거가 확인되지 않음이면 확인됨이 못 됨)
초안 검사(인용 번호·문단·조문이 앞 결과와 맞는지, 이슈 #40)는 여기서 하지 않는다.
"""

import logging

from pydantic import BaseModel, ConfigDict, Field, model_validator

from patent_ai.core.f4_response_draft.config import F4Options, load_f4_options
from patent_ai.core.f4_response_draft.directions import f3_results, to_json, unit_variables
from patent_ai.core.f4_response_draft.inputs import F4Input, legal_bundle_for
from patent_ai.core.f4_response_draft.llm_call import call_with_one_retry
from patent_ai.core.llm.errors import ModelCallLimitExceeded
from patent_ai.core.llm.limits import RunContext
from patent_ai.core.schemas.common import (
    Evidence,
    Flag,
    Status,
    StatusValue,
    UnverifiedReason,
    worst_status,
)
from patent_ai.core.schemas.direction import (
    AmendmentKind,
    DirectionCandidate,
    DirectionCandidates,
)
from patent_ai.core.schemas.drafts import AmendedClaim, BasedOn, Drafts, OpinionKey, OpinionSection
from patent_ai.core.schemas.judgment_unit import JudgmentUnit
from patent_ai.core.schemas.propagation import propagate

logger = logging.getLogger(__name__)

STEP = "f4.opinion"

# 의견서 칸 제목 (순서는 OpinionKey 선언 순서)
SECTION_TITLES: dict[OpinionKey, str] = {
    OpinionKey.CASE_INFO: "사건 정보",
    OpinionKey.POINTS: "지적 요지",
    OpinionKey.RESPONSE: "대응과 근거",
    OpinionKey.AMENDMENT: "보정 설명",
    OpinionKey.CLOSING: "마무리",
}
# 사건 전체에 한 번만 쓰는 칸: 첫 묶음 것만 쓴다. 나머지 칸은 묶음 순서대로 이어 붙인다
_ONCE = (OpinionKey.CASE_INFO, OpinionKey.CLOSING)
ALL_DRAFT_INPUTS_CHECKED = "초안이 기대는 입력 모두 확인됨"


# ---- 모델 출력 모양 (묶음 하나의 의견서 칸) ----
class OpinionOut(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    case_info: str
    points: str
    response: str
    amendment: str | None  # 보정이 없는 방향이면 null
    closing: str


class OpinionPart(BaseModel):
    """의견서 부분 결과 (저장 스키마가 아닌 내부 모델). Drafts로 묶는 것은 drafts_from_opinion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sections: list[OpinionSection]  # 모든 묶음이 보류면 빈 목록
    based_on: list[BasedOn]  # 초안을 만든 묶음과 그 후보
    held_units: list[str]  # 고른 후보가 없어 보류한 묶음 (사람이 고르면 다시 만든다)
    status: Status
    evidence: list[Evidence] = Field(default_factory=list)
    flags: list[Flag] = Field(default_factory=list)


def has_amendment(candidate: DirectionCandidate) -> bool:
    """고른 방향에 실제로 고치는 청구항이 있나 (unchanged만 있으면 보정 없음)."""
    return any(a.kind != AmendmentKind.UNCHANGED for a in candidate.amendment_core)


def selected_candidate(result: DirectionCandidates) -> DirectionCandidate | None:
    """묶음에서 고른 후보 (AI 기본값이든 사람 선택이든).

    고르지 않았거나 사람이 직접 쓴 방향이면 None (그 묶음 초안은 보류).
    """
    if result.selection is None or result.selection.candidate_id is None:
        return None
    return next(c for c in result.candidates if c.candidate_id == result.selection.candidate_id)


def _sections_of(out: OpinionOut, amended: bool) -> dict[OpinionKey, OpinionSection]:
    """모델 답 하나를 칸으로. 빈 글·보정 설명 어긋남은 ValueError (출력 검사에도 쓴다)."""
    if amended and out.amendment is None:
        raise ValueError("고른 방향에 보정이 있는데 amendment(보정 설명)가 null")
    if not amended and out.amendment is not None:
        raise ValueError("고른 방향에 보정이 없으면 amendment는 null이어야 함")
    texts = {
        OpinionKey.CASE_INFO: out.case_info,
        OpinionKey.POINTS: out.points,
        OpinionKey.RESPONSE: out.response,
        OpinionKey.AMENDMENT: out.amendment,
        OpinionKey.CLOSING: out.closing,
    }
    # ai_text가 비면 OpinionSection 검사가 거부한다
    return {
        key: OpinionSection(key=key, title=SECTION_TITLES[key], ai_text=text)
        for key, text in texts.items()
        if text is not None
    }


def _checked_schema(amended: bool) -> type[OpinionOut]:
    """이 묶음에 맞춘 출력 검사 스키마. 칸을 만들 수 없는 답은 출력 검사 실패 -> 한 번 다시 부름."""

    class CheckedOpinionOut(OpinionOut):
        @model_validator(mode="after")
        def _칸으로_만들_수_있어야_한다(self) -> CheckedOpinionOut:
            _sections_of(self, amended)
            return self

    return CheckedOpinionOut


def _prompt_variables(
    inp: F4Input, unit: JudgmentUnit, chosen: DirectionCandidate, f3: list, bundle
) -> dict[str, str]:
    """프롬프트 변수. 방향은 고른 후보 하나만 싣는다 (다른 후보는 어디에도 넣지 않음)."""
    variables = unit_variables(inp, unit, f3, bundle, max_candidates=1)
    del variables["max_candidates"]  # 방향 후보 단계에만 있는 자리
    oa = inp.oa
    variables["case_info"] = to_json(
        {
            "application_number": oa.application_number.raw_text,
            "dispatch_number": oa.dispatch_number.raw_text,
            "notice_date": oa.notice_date.raw_text,
            "response_due": oa.response_due.raw_text,
        }
    )
    variables["selected"] = to_json(
        chosen.model_dump(
            mode="json",
            include={
                "coarse",
                "name",
                "confidence",
                "reason",
                "checks",
                "per_rejection",
                "amendment_core",
                "rebuttal",
            },
        )
    )
    return variables


def build_opinion(
    inp: F4Input,
    directions: list[DirectionCandidates],
    ctx: RunContext,
    *,
    options: F4Options | None = None,
) -> OpinionPart:
    """방향을 고른 묶음마다 의견서 칸을 만들어 order 순으로 잇는다.

    고른 후보가 없는 묶음은 held_units에 넣고 건너뛴다 (다른 묶음은 진행).
    모델 호출 실패는 결과로 바꾸지 않고 예외를 그대로 던진다.
    """
    options = options or load_f4_options()
    by_unit = {d.unit_id: d for d in directions}
    # 방향 후보 결과가 없는 묶음을 조용히 빼면 대응 누락이 된다. 부르기 전에 멈춘다
    missing = [u.unit_id for u in inp.units if u.unit_id not in by_unit]
    if missing:
        raise ValueError(f"방향 후보 결과가 없는 판단 단위: {missing}")
    if len(inp.units) > options.max_units:
        raise ModelCallLimitExceeded("max_units", len(inp.units), options.max_units)
    if not inp.units:
        logger.warning("f4.opinion %s: 판단 단위가 0개라 의견서를 만들지 않음", inp.oa.oa_id)

    per_unit: list[dict[OpinionKey, OpinionSection]] = []
    based_on: list[BasedOn] = []
    held: list[str] = []
    statuses: list[Status] = []
    evidence: list[Evidence] = []
    legal_unverified = False
    for unit in sorted(inp.units, key=lambda u: (u.order, u.unit_id)):
        chosen = selected_candidate(by_unit[unit.unit_id])
        if chosen is None:
            sel = by_unit[unit.unit_id].selection
            if sel is not None and sel.written_direction is not None:
                logger.warning(
                    "f4.opinion %s: 사람이 쓴 방향이라 이 묶음 의견서는 AI가 만들지 않음",
                    unit.unit_id,
                )
            else:
                logger.warning(
                    "f4.opinion %s: 고른 방향이 없어 이 묶음 의견서는 보류", unit.unit_id
                )
            held.append(unit.unit_id)
            continue
        f3, bundle = f3_results(inp, unit), legal_bundle_for(inp, unit)
        amended = has_amendment(chosen)
        variables = _prompt_variables(inp, unit, chosen, f3, bundle)
        out = call_with_one_retry(STEP, variables, _checked_schema(amended), ctx)
        per_unit.append(_sections_of(out, amended))
        based_on.append(BasedOn(unit_id=unit.unit_id, candidate_id=chosen.candidate_id))
        # 초안은 고른 후보와 법률 근거 묶음에 기댄다
        statuses += [chosen.status, bundle.status]
        legal_unverified = legal_unverified or bundle.status.value != StatusValue.CONFIRMED
        evidence += [e for e in chosen.evidence if e not in evidence]

    # 같은 칸끼리 묶음 순서대로 잇는다. 사건 정보·마무리는 첫 묶음 것만
    sections: list[OpinionSection] = []
    for key in OpinionKey:
        texts = [s[key].ai_text for s in per_unit if key in s]
        if not texts:
            continue
        text = texts[0] if key in _ONCE else "\n\n".join(texts)
        sections.append(OpinionSection(key=key, title=SECTION_TITLES[key], ai_text=text))

    flags: list[Flag] = []
    if held:
        flags.append(Flag.NEEDS_HUMAN_JUDGMENT)  # 사람이 방향을 골라야 그 묶음 초안이 나온다
    if legal_unverified:
        flags.append(Flag.NEEDS_HUMAN_REVIEW)  # 초안에 법률 근거 확인 필요 표시가 남아 있다
    if not sections and inp.units:
        logger.warning("f4.opinion %s: 모든 묶음이 보류라 의견서 칸이 없음", inp.oa.oa_id)
    status = (
        propagate(statuses)
        if statuses  # 만든 칸이 없으면 "영향 없음 = 확인됨"이 아니라 확인되지 않음
        else Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
    )
    return OpinionPart(
        sections=sections,
        based_on=based_on,
        held_units=held,
        status=status,
        evidence=evidence,
        flags=flags,
    )


def drafts_from_opinion(
    oa_id: str,
    part: OpinionPart,
    *,
    claims: list[AmendedClaim] | None = None,
    more_statuses: list[Status] | None = None,
    more_flags: list[Flag] | None = None,
) -> Drafts | None:
    """의견서 부분 결과를 Drafts(OA 하나에 하나)로 묶는다. 보정 청구항 단계가 claims를 끼운다.

    의견서 칸이 하나도 없으면(모든 묶음 보류) None. status는 의견서와 more_statuses 중 가장 나쁜 값.
    """
    if not part.sections:
        logger.warning("f4 %s: 의견서 칸이 없어 초안(Drafts)을 만들지 않음 (보류)", oa_id)
        return None
    flags = list(part.flags)
    flags += [f for f in more_flags or [] if f not in flags]
    return Drafts(
        draft_id=f"dr:{oa_id}",
        based_on=part.based_on,
        opinion=part.sections,
        claims=claims or [],
        status=worst_status([part.status, *(more_statuses or [])], ALL_DRAFT_INPUTS_CHECKED),
        evidence=part.evidence,
        flags=flags,
    )
