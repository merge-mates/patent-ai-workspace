"""보정 청구항 초안 단계: 고른 방향에 보정이 있는 묶음마다 모델을 한 번 불러 검토용 초안을 만든다.

청구항을 고쳐 쓰는 것은 모델(프롬프트)이 한다. 코드는 확인만 한다:
- 의견서를 만든 묶음과 그 후보로만 만든다 (의견서 다음 단계. 의견서가 보류한 묶음은 여기서도 보류)
- 모델이 준 명세서 근거는 최초 명세서 그 쪽 글자와 대조해 통과한 것만 남긴다 (지어낸 근거는 버림)
- 근거를 못 찾아도 초안(ai_text)은 남기고 근거 위치만 비운다 (확인되지 않음 + 직접 검토 필요)
- 묶음 밖 청구항을 고치거나, 고치기로 한 청구항이 빠지면 출력 검사 실패 (한 번 다시 부름)
보정이 적법한지(신규사항 추가 등)는 판단하지 않는다.
"바뀐 부분"은 저장하지 않고 diff_claim으로 비교만 한다.
"""

import difflib
import logging

from pydantic import BaseModel, ConfigDict, Field, model_validator

from patent_ai.core.f1_oa_reader.verify import raw_text_on_page
from patent_ai.core.f4_response_draft.config import F4Options, load_f4_options
from patent_ai.core.f4_response_draft.directions import f3_results, to_json, unit_variables
from patent_ai.core.f4_response_draft.inputs import F4Input, legal_bundle_for
from patent_ai.core.f4_response_draft.llm_call import call_with_one_retry
from patent_ai.core.f4_response_draft.opinion import OpinionPart, drafts_from_opinion, has_amendment
from patent_ai.core.llm.errors import ModelCallLimitExceeded
from patent_ai.core.llm.limits import RunContext
from patent_ai.core.schemas.common import Evidence, Flag, Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.direction import (
    AmendmentKind,
    DirectionCandidate,
    DirectionCandidates,
)
from patent_ai.core.schemas.document import PageText
from patent_ai.core.schemas.drafts import AmendedClaim, Drafts
from patent_ai.core.schemas.judgment_unit import JudgmentUnit

logger = logging.getLogger(__name__)

STEP = "f4.amendment"

HELD_NO_SELECTION = "확신이 낮아 방향을 미리 고르지 않은 묶음입니다. 방향을 고르면 초안을 만듭니다."
HELD_NO_CLAIM_TEXT = (
    "OA 당시 청구항 글자가 입력에 없어 초안을 만들지 못했습니다. 청구항 자료를 확인해 주세요."
)
SPEC_BASIS_CHECKED = "명세서 근거 위치를 그 쪽 원문과 대조"
# 보정 초안에 늘 붙여 보일 문구. 결과 스키마(v0)에 칸이 없어 상수로 둔다 (화면·API가 같이 보인다)
LEGALITY_NOTICE = "검토용 초안이며 보정의 적법성은 판단하지 않았습니다"


# ---- 모델 출력 모양 ----
class BasisOut(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    page: int
    location: str | None = None
    raw_text: str


class AmendedClaimOut(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: int
    text: str
    spec_basis: list[BasisOut]


class AmendmentOut(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claims: list[AmendedClaimOut]


class AmendmentPart(BaseModel):
    """보정 청구항 부분 결과 (저장 스키마가 아닌 내부 모델). Drafts로 묶는 것은 assemble_drafts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claims: list[AmendedClaim]  # 청구항 번호 순, 번호 중복 없음
    statuses: list[Status]  # claims와 같은 순서: 그 청구항의 명세서 근거 확인 상태
    held_units: list[str]  # 초안을 보류한 묶음
    flags: list[Flag] = Field(default_factory=list)


def _check_output(out: AmendmentOut, allowed: set[int], required: set[int]) -> None:
    """모델 답이 이 묶음의 것인지 확인한다. 어긋나면 ValueError (출력 검사 실패)."""
    nums = [c.claim for c in out.claims]
    if len(set(nums)) != len(nums):
        raise ValueError(f"같은 청구항이 두 번 나옴: {nums}")
    if set(nums) - allowed:
        raise ValueError(
            f"청구항 {sorted(set(nums) - allowed)}는 이 판단 단위의 청구항 {sorted(allowed)} 밖"
        )
    if required - set(nums):
        raise ValueError(f"고른 방향이 고치기로 한 청구항 {sorted(required - set(nums))}가 빠짐")
    for c in out.claims:
        if not c.text.strip():
            raise ValueError(f"청구항 {c.claim}의 text가 비어 있음")


def _checked_schema(allowed: set[int], required: set[int]) -> type[AmendmentOut]:
    """이 묶음에 맞춘 출력 검사 스키마. 떨어진 답은 ModelOutputInvalid -> 한 번 다시 부름."""

    class CheckedAmendmentOut(AmendmentOut):
        @model_validator(mode="after")
        def _이_묶음의_청구항만(self) -> CheckedAmendmentOut:
            _check_output(self, allowed, required)
            return self

    return CheckedAmendmentOut


# ---- 명세서 근거 대조 ----
def _verified_basis(
    given: list[BasisOut], spec: PageText | None, unit_id: str, claim: int
) -> list[Evidence]:
    """모델이 준 근거 중 최초 명세서 그 쪽에 글자가 실제로 있는 것만 Evidence로 남긴다."""
    if spec is None:
        return []
    kept: list[Evidence] = []
    for b in given:
        if raw_text_on_page(spec, b.page, b.raw_text):
            kept.append(
                Evidence(
                    document_id=spec.document_id,
                    page=b.page,
                    location=b.location,
                    raw_text=b.raw_text,
                )
            )
        else:
            logger.warning(
                "f4.amendment %s 청구항 %d: 명세서 %d쪽에서 근거 글자를 못 찾아 버림",
                unit_id,
                claim,
                b.page,
            )
    return kept


def _basis_status(basis: list[Evidence], spec: PageText | None, needs_basis: bool) -> Status:
    """청구항 하나의 명세서 근거 상태. 못 찾음은 "없음"이 아니라 확인되지 않음이다."""
    if basis or not needs_basis:
        return Status(value=StatusValue.CONFIRMED, checked=SPEC_BASIS_CHECKED)
    reason = UnverifiedReason.BODY_MISSING if spec is None else UnverifiedReason.EVIDENCE_REJECTED
    return Status(value=StatusValue.UNVERIFIED, reason=reason)


def _spec_text(spec: PageText | None) -> str:
    if spec is None:
        return "(최초 명세서가 입력에 없음. spec_basis는 빈 목록으로 둡니다)"
    return "\n\n".join(f"[쪽 {p.page}]\n{p.text}" for p in spec.pages)


def _held(unit: JudgmentUnit, texts: dict[int, str], reason: str) -> list[AmendedClaim]:
    """묶음의 청구항을 초안 없이 보류로 둔다."""
    return [
        AmendedClaim(
            claim=n,
            unit_id=unit.unit_id,
            before=texts.get(n, ""),
            ai_text=None,
            spec_basis=[],
            held_reason=reason,
        )
        for n in unit.claims
    ]


def build_amendments(
    inp: F4Input,
    directions: list[DirectionCandidates],
    opinion: OpinionPart,
    ctx: RunContext,
    *,
    options: F4Options | None = None,
    limit_note: str = "",
) -> AmendmentPart:
    """의견서를 만든 묶음 가운데 보정이 있는 묶음마다 보정 청구항 초안을 만든다 (order 순).

    opinion.based_on의 후보로만 만들어 의견서와 같은 방향을 쓴다. opinion.held_units는 보류.
    limit_note는 프롬프트에 끼울 보정 제한 문구 자리다 (최후거절이유통지 제한, 지금은 빈 글자).
    모델 호출 실패는 결과로 바꾸지 않고 예외를 그대로 던진다.
    """
    options = options or load_f4_options()
    if len(inp.units) > options.max_units:
        raise ModelCallLimitExceeded("max_units", len(inp.units), options.max_units)
    chosen_id = {b.unit_id: b.candidate_id for b in opinion.based_on}
    candidates = {c.candidate_id: c for d in directions for c in d.candidates}
    # 의견서가 다루지 않은 묶음을 조용히 빼면 대응 누락이 된다. 부르기 전에 멈춘다
    unknown = [
        u.unit_id
        for u in inp.units
        if u.unit_id not in opinion.held_units
        and candidates.get(chosen_id.get(u.unit_id, "")) is None
    ]
    if unknown:
        raise ValueError(f"의견서 단계 결과에 없는 판단 단위(또는 후보): {unknown}")

    texts = {c.claim: c.text for c in inp.claims_text}
    taken: dict[int, tuple[AmendedClaim, Status]] = {}  # 청구항 번호 -> 먼저 가진 묶음의 초안
    held_units: list[str] = []
    flags: list[Flag] = []

    def flag(f: Flag) -> None:
        if f not in flags:
            flags.append(f)

    def take(unit: JudgmentUnit, claim: AmendedClaim, status: Status) -> None:
        # 한 청구항이 여러 묶음에 걸치면 order가 앞선 묶음 것을 두고, 뒤 묶음 것은 덮어쓰지 않는다
        if claim.claim in taken:
            owner = taken[claim.claim][0].unit_id
            logger.warning(
                "f4.amendment %s: 청구항 %d는 앞선 묶음 %s가 이미 가짐 (덮어쓰지 않음)",
                unit.unit_id,
                claim.claim,
                owner,
            )
            flag(Flag.NEEDS_HUMAN_REVIEW)
            return
        taken[claim.claim] = (claim, status)

    held_status = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
    for unit in sorted(inp.units, key=lambda u: (u.order, u.unit_id)):
        if unit.unit_id in opinion.held_units:
            logger.warning(
                "f4.amendment %s: 고른 방향이 없어 이 묶음 보정 초안은 보류", unit.unit_id
            )
            held_units.append(unit.unit_id)
            flag(Flag.NEEDS_HUMAN_JUDGMENT)
            for claim in _held(unit, texts, HELD_NO_SELECTION):
                take(unit, claim, held_status)
            continue
        chosen: DirectionCandidate = candidates[chosen_id[unit.unit_id]]
        if not has_amendment(chosen):
            continue  # 보정 없이 반박하는 방향: 보정 청구항을 만들지 않는다
        kinds = {a.claim: a.kind for a in chosen.amendment_core}
        required = {n for n, kind in kinds.items() if kind != AmendmentKind.UNCHANGED}
        if required - texts.keys():
            # OA 당시 글자 없이는 "앞" 글자도 비교도 없다. 모델을 부르지 않고 그 묶음을 보류한다
            logger.warning(
                "f4.amendment %s: 청구항 글자가 입력에 없어 보류 %s",
                unit.unit_id,
                sorted(required - texts.keys()),
            )
            held_units.append(unit.unit_id)
            flag(Flag.NEEDS_HUMAN_REVIEW)
            for claim in _held(unit, texts, HELD_NO_CLAIM_TEXT):
                take(unit, claim, held_status)
            continue
        allowed = {n for n in [*unit.claims, *unit.read_with] if n in texts}

        f3, bundle = f3_results(inp, unit), legal_bundle_for(inp, unit)
        variables = unit_variables(inp, unit, f3, bundle, max_candidates=1)
        del variables["max_candidates"], variables["legal"]  # 이 프롬프트에 없는 자리
        variables["selected"] = to_json(
            chosen.model_dump(
                mode="json", include={"coarse", "name", "reason", "per_rejection", "amendment_core"}
            )
        )
        variables["spec"] = _spec_text(inp.spec)
        variables["limit_note"] = limit_note
        out = call_with_one_retry(STEP, variables, _checked_schema(allowed, required), ctx)

        for c in out.claims:
            basis = _verified_basis(c.spec_basis, inp.spec, unit.unit_id, c.claim)
            # 삭제하는 청구항은 명세서 근거 위치를 요구하지 않는다 (더한 내용이 없음)
            status = _basis_status(basis, inp.spec, kinds.get(c.claim) != AmendmentKind.DELETE)
            if status.value != StatusValue.CONFIRMED:
                logger.warning(
                    "f4.amendment %s 청구항 %d: 명세서 근거 위치를 확인하지 못함 (%s)",
                    unit.unit_id,
                    c.claim,
                    status.reason,
                )
                flag(Flag.NEEDS_HUMAN_REVIEW)
            take(
                unit,
                AmendedClaim(
                    claim=c.claim,
                    unit_id=unit.unit_id,
                    before=texts[c.claim],
                    ai_text=c.text,
                    spec_basis=basis,
                    held_reason=None,
                ),
                status,
            )

    ordered = [taken[n] for n in sorted(taken)]
    return AmendmentPart(
        claims=[c for c, _ in ordered],
        statuses=[s for _, s in ordered],
        held_units=held_units,
        flags=flags,
    )


def assemble_drafts(oa_id: str, opinion: OpinionPart, amendment: AmendmentPart) -> Drafts | None:
    """의견서와 보정 청구항을 Drafts 하나로 묶는다. 의견서 칸이 없으면(모든 묶음 보류) None."""
    # 보류한 청구항의 상태는 초안 전체 status에 넣지 않는다 (보류는 flags와 held_reason으로 보임)
    made = [s for c, s in zip(amendment.claims, amendment.statuses, strict=True) if c.ai_text]
    return drafts_from_opinion(
        oa_id, opinion, claims=amendment.claims, more_statuses=made, more_flags=amendment.flags
    )


def diff_claim(before: str, after: str | None) -> list[dict[str, str]]:
    """보정 앞뒤 청구항 글자의 바뀐 부분 (화면·API용, 저장하지 않음).

    조각마다 {"op": equal|replace|insert|delete, "before": 앞 글자, "after": 뒤 글자}.
    before들을 이으면 앞 글자, after들을 이으면 뒤 글자가 된다. 보류(after 없음)면 빈 목록.
    글자를 견줄 뿐이고 뜻이 바뀌었는지는 보지 않는다.
    """
    if after is None:
        return []
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    return [
        {"op": op, "before": before[a1:a2], "after": after[b1:b2]}
        for op, a1, a2, b1, b2 in matcher.get_opcodes()
    ]
