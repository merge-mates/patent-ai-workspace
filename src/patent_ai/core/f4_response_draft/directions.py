"""방향 후보 단계: 판단 단위(묶음)마다 모델을 한 번 불러 DirectionCandidates를 만든다.

방향을 떠올리고 순위·이유·확신도를 매기는 것은 모델(프롬프트)이 한다. 코드는 확인만 한다:
- 모델 답이 스키마 규칙(확신 낮음이면 순위 없음 등)과 설정 상한을 지키는지 (어기면 한 번 다시 부름)
- status는 앞 단계(F3·F2) 결과에서 전파하고, 근거는 F3 결과의 것만 붙인다
  (모델이 준 근거는 받지 않음)
- 보정 제한은 OA 통지 종류 사실을 그대로 옮긴다 (적법성 판정 아님)
AI는 방향을 확정하지 않는다. 1등을 AI 기본값으로 미리 골라 둘 뿐이고, 고르는 것은 사람이다.
"""

import json
import logging

from pydantic import BaseModel, ConfigDict, model_validator

from patent_ai.core.bundle_errors import (
    BUNDLE_ERRORS,
    failed_status,
    held_error_status,
    is_limit,
    raise_if_all_failed,
    why,
)
from patent_ai.core.f4_response_draft.config import F4Options, load_f4_options
from patent_ai.core.f4_response_draft.inputs import F4Input, legal_bundle_for
from patent_ai.core.f4_response_draft.llm_call import call_with_one_retry
from patent_ai.core.llm.limits import RunContext
from patent_ai.core.schemas.common import (
    Candidate,
    Evidence,
    ExtractedValue,
    Flag,
    Origin,
    Status,
    StatusValue,
    UnverifiedReason,
)
from patent_ai.core.schemas.comparison import ComparisonTable
from patent_ai.core.schemas.direction import (
    AmendmentCore,
    AmendmentLimit,
    CoarseDirection,
    Confidence,
    DirectionCandidate,
    DirectionCandidates,
    DirectionSelection,
    Rebuttal,
    RebuttalType,
    RejectionResponse,
    summarize_direction_status,
)
from patent_ai.core.schemas.judgment_unit import JudgmentUnit
from patent_ai.core.schemas.legal_evidence import LegalEvidenceBundle
from patent_ai.core.schemas.oa_result import NoticeKind, OAResult, Rejection
from patent_ai.core.schemas.propagation import propagate

logger = logging.getLogger(__name__)

STEP = "f4.direction"

# 결과 스키마(v0)에 이 문구를 담을 칸이 없어 상수로 둔다. run_f4가 F4Output.rank_notice에 싣는다
RANK_NOTICE = "순위는 검토 순서 제안이고 등록 가능성을 보증하지 않는다"
# 보정 제한 스위치가 켜져 있는데 통지 종류를 모를 때 후보마다 붙이는 확인 사항
NOTICE_KIND_CHECK = "통지 종류 확인 필요 (최후거절이유통지이면 보정할 수 있는 범위가 제한됨)"
# 보정 제한 스위치가 꺼져 있는데 통지 종류가 최후일 때 후보마다 붙이는 확인 사항
NOTICE_FINAL_UNLIMITED = "보정 제한을 적용하지 않은 초안 (최후거절이유통지, 직접 검토 필요)"


# ---- 모델 출력 모양 (결과 스키마와 따로 둔다: status·근거·origin·ID는 코드가 채운다) ----
class RebuttalOut(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: RebuttalType
    summary: str


class CandidateOut(BaseModel):
    # 모르는 칸은 거부한다: 모델이 근거(evidence)·status를 지어 붙인 답은 출력 검사에 떨어진다
    model_config = ConfigDict(frozen=True, extra="forbid")

    rank: int | None
    coarse: CoarseDirection
    name: str
    confidence: Confidence
    reason: str
    checks: list[str]
    per_rejection: list[RejectionResponse]
    amendment_core: list[AmendmentCore]
    rebuttal: RebuttalOut | None


class DirectionsOut(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidates: list[CandidateOut]


# ---- 보정 제한: OA 통지 종류 사실 그대로 ----
_LIMIT_BY_KIND = {
    NoticeKind.INITIAL: AmendmentLimit.INITIAL,
    NoticeKind.FINAL: AmendmentLimit.FINAL,
}


def amendment_limit_of(oa: OAResult) -> ExtractedValue[AmendmentLimit]:
    """통지 종류(initial/final/unknown)를 보정 제한 칸으로 옮긴다. 스위치와 상관없이 늘 채운다.

    모르면(unknown) 값 없이 원래 status·이유를 그대로 둔다. 여기서 종류를 짐작하지 않는다.
    """
    kind = oa.notice_kind
    value = _LIMIT_BY_KIND.get(kind.value) if kind.value is not None else None
    status = kind.status
    if value is None and status.value == StatusValue.CONFIRMED:
        # 값이 없는데 확인됨일 수는 없다 (스키마 규칙). 못 뽑은 것으로 둔다
        status = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
    return ExtractedValue[AmendmentLimit](
        value=value,
        raw_text=kind.raw_text,
        page=kind.page,
        status=status,
        # 충돌이면 후보도 같이 옮긴다 (unknown 후보는 값 없음)
        candidates=[
            Candidate[AmendmentLimit](
                value=_LIMIT_BY_KIND.get(c.value) if c.value is not None else None,
                raw_text=c.raw_text,
                page=c.page,
                source=c.source,
            )
            for c in kind.candidates
        ],
    )


# ---- 앞 단계 결과에서 status·근거 모으기 ----
def f3_results(inp: F4Input, unit: JudgmentUnit) -> list:
    """이 묶음의 F3 결과 (대비표 + 명확성 검토)."""
    tables = [t for t in inp.tables if t.unit_id == unit.unit_id]
    clarity = [c for c in inp.clarity if c.unit_id == unit.unit_id]
    return [*tables, *clarity]


def _status_of(
    f3: list, bundle: LegalEvidenceBundle, unit: JudgmentUnit, gaps: list[Status]
) -> Status:
    """후보 status: F3 결과·대비 못 한 것·법률 근거 묶음이 모두 확인됨이어야 확인됨."""
    # F3가 호출 상한으로 못 한 것이 있으면 그 이유(limit_reached)를 잃지 않는다.
    # F3는 상한에 닿은 묶음의 대비표를 남기지 않으므로 "F3 결과 없음"보다 먼저 본다
    limited = next((g for g in gaps if g.reason == UnverifiedReason.LIMIT_REACHED), None)
    if limited is not None:
        return limited
    if not f3:
        # 기대는 F3 결과가 없으면 "영향 없음"이 아니라 확인되지 않음이다
        logger.warning("f4.direction %s: 이 묶음의 F3 결과가 없음 (input_unverified)", unit.unit_id)
        return Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.INPUT_UNVERIFIED)
    return propagate([*(r.status for r in f3), *gaps, bundle.status])


class F3Gaps(BaseModel):
    """F3가 이 묶음에서 대비하지 못한 것 (F4 design 3-1). 후보 status·flags·확인 사항에 옮긴다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    statuses: list[Status]  # 후보 status 전파에 더할 값
    checks: list[str]  # 후보마다 붙일 확인 사항
    needs_review: bool  # 후보 flags에 needs_human_review


def _held_for(task: str, unit_id: str) -> bool:
    """F3 보류 작업 이름이 이 단위 것인가 (`f3_compare:<unit_id>`, `...:claim2` 등)."""
    for step in ("f3_compare", "f3_clarity"):
        head = f"{step}:{unit_id}"
        if task == head or task.startswith(head + ":"):
            return True
    return False


def f3_gaps(inp: F4Input, unit: JudgmentUnit, f3: list) -> F3Gaps:
    """대비 못 한 인용문헌(`compared=false`), F3 결과의 직접 검토 필요, 단위 안 보류를 모은다.

    표 status는 대비한 줄만 모으므로, 여기서 따로 옮기지 않으면 F2가 붙은 뒤
    결합 문헌 하나를 못 읽은 후보가 "확인됨" + 표시 없음이 된다.
    """
    statuses: list[Status] = []
    checks: list[str] = []
    needs_review = False
    for result in f3:
        if Flag.NEEDS_HUMAN_REVIEW in result.flags:
            needs_review = True
        # 대비표만 인용문헌 목록(citations)이 있다. 명확성 검토 결과는 건너뛴다
        if not isinstance(result, ComparisonTable):
            continue
        for c in result.citations:
            if not c.compared and c.skipped_status is not None:
                statuses.append(c.skipped_status)
                checks.append(f"인용문헌 {c.label}({c.number}) 대비 못 함: {c.skipped_reason}")
    held = [h for h in inp.held_tasks if _held_for(h.task, unit.unit_id)]
    for h in held:
        # F3가 호출 상한(limit_reached)으로 보류한 것은 그 이유를 유지한다
        statuses.append(
            held_error_status(h.task)
            or Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
        )
        checks.append(f"F3 보류: {h.waiting_for}")
    if checks:
        logger.warning("f4.direction %s: F3가 대비하지 못한 것 %s", unit.unit_id, checks)
    return F3Gaps(statuses=statuses, checks=checks, needs_review=needs_review or bool(checks))


LEGAL_REVIEW_CHECK = "법률 근거: 근거 검토 전 (직접 검토 필요)"


def legal_needs_review(bundle: LegalEvidenceBundle) -> bool:
    """법률 근거 묶음이나 그 주장에 직접 검토 필요가 있나 (#28: 근거 검토 전 F2 묶음).

    묶음 status는 주장 status만 모아 확인됨이 될 수 있어, 주장의 표시를 따로 옮기지 않으면
    근거 검토를 안 한 법률 근거가 후보에서 "확인됨 + 표시 없음"으로 보인다.
    """
    return Flag.NEEDS_HUMAN_REVIEW in bundle.flags or any(
        Flag.NEEDS_HUMAN_REVIEW in c.flags for c in bundle.claims
    )


def _evidence_of(f3: list) -> list[Evidence]:
    """F3 결과에 붙은 근거만 모은다 (대비표 줄 + 명확성 결과의 명세서 정의). 같은 근거는 한 번만."""
    found: list[Evidence] = []
    for result in f3:
        # 명확성 결과는 evidence가 비고 근거가 spec_definition에 있다: 같이 모아야 안 빠진다
        spec_definition = getattr(result, "spec_definition", None)
        for e in [
            *result.evidence,
            *(e for row in getattr(result, "rows", []) for e in row.evidence),
            *([spec_definition] if spec_definition is not None else []),
        ]:
            if e not in found:
                found.append(e)
    return found


# ---- 모델 답 -> 결과 (출력 검사에도 같은 함수를 쓴다) ----
def _build(
    out: DirectionsOut,
    unit: JudgmentUnit,
    oa: OAResult,
    status: Status,
    evidence: list[Evidence],
    limit: ExtractedValue[AmendmentLimit],
    max_candidates: int,
    extra_flags: list[Flag] | None = None,
    extra_checks: list[str] | None = None,
    candidate_flags: list[Flag] | None = None,
) -> DirectionCandidates:
    """모델 답 하나를 DirectionCandidates로 만든다. 규칙을 어기면 ValueError(스키마 검사 포함)."""
    if len(out.candidates) > max_candidates:
        raise ValueError(f"후보가 {len(out.candidates)}개로 상한 {max_candidates}개를 넘음")
    known_rejections = {r.no for r in oa.rejections}
    allowed_claims = {*unit.claims, *unit.read_with}
    # 후보 목록은 모델이 낸 순서 그대로 둔다 (다시 줄 세우지 않음). candidate_id 번호도 그 순서다.
    # 확신 낮은 후보는 rank가 없어, "모델이 먼저 낸 후보"는 이 순서로만 알 수 있다 (채점이 읽는다).
    # 화면에 보일 순위는 rank 칸이고, 확신 낮음이면 여전히 순위 없음·미리 고르지 않음이다
    candidates: list[DirectionCandidate] = []
    for n, c in enumerate(out.candidates, start=1):
        if not c.name.strip():
            raise ValueError("name이 비어 있음")
        answered = [p.rejection for p in c.per_rejection]
        if unit.rejection not in answered:
            raise ValueError(f"per_rejection에 이 묶음의 거절이유 {unit.rejection}이 없음")
        if set(answered) - known_rejections:
            unknown = sorted(set(answered) - known_rejections)
            raise ValueError(f"per_rejection에 OA에 없는 거절이유 번호: {unknown}")
        claims = [a.claim for a in c.amendment_core]
        if len(set(claims)) != len(claims):
            raise ValueError("amendment_core에 같은 청구항이 두 번 나옴")
        if set(claims) - allowed_claims:
            raise ValueError(
                f"amendment_core의 청구항 {sorted(set(claims) - allowed_claims)}는 "
                f"이 묶음의 청구항 {sorted(allowed_claims)} 밖"
            )
        low = c.confidence == Confidence.LOW
        candidates.append(
            DirectionCandidate(
                candidate_id=f"{unit.unit_id}:d{n}",
                rank=c.rank,
                coarse=c.coarse,
                name=c.name,
                confidence=c.confidence,
                reason=c.reason,
                checks=[*c.checks, *(extra_checks or [])],
                per_rejection=list(c.per_rejection),
                amendment_core=list(c.amendment_core),
                # 반박의 거절이유 종류는 판단 단위에서 가져온다 (유형이 안 맞으면 거부됨)
                rebuttal=None
                if c.rebuttal is None
                else Rebuttal(
                    rejection_kind=unit.rejection_kind,
                    type=c.rebuttal.type,
                    summary=c.rebuttal.summary,
                ),
                status=status,
                evidence=evidence,  # F3 결과의 근거만. 모델 답에는 근거 칸이 없다
                flags=[*([Flag.NEEDS_HUMAN_JUDGMENT] if low else []), *(candidate_flags or [])],
            )
        )
    first = next((c for c in candidates if c.rank == 1), None)
    return DirectionCandidates(
        unit_id=unit.unit_id,
        candidates=candidates,
        # 1등만 AI 기본값으로 미리 고른다. 순위 있는 후보가 없으면(확신 낮음·0개) 고르지 않는다
        selection=None
        if first is None
        else DirectionSelection(candidate_id=first.candidate_id, origin=Origin.AI_DEFAULT),
        amendment_limit=limit,
        status=summarize_direction_status(candidates, limit),
        evidence=evidence,
        flags=[*([] if first is not None else [Flag.NEEDS_HUMAN_JUDGMENT]), *(extra_flags or [])],
    )


def _checked_schema(build) -> type[DirectionsOut]:
    """이 묶음에 맞춘 출력 검사 스키마. 결과를 한 번 만들어 보아, 못 만들면 출력 검사 실패가 된다.

    call_model은 output_schema 검사에 떨어진 답을 ModelOutputInvalid로 던지고,
    그러면 call_with_one_retry가 검사 오류를 붙여 한 번 더 부른다.
    """

    class CheckedDirectionsOut(DirectionsOut):
        @model_validator(mode="after")
        def _결과로_만들_수_있어야_한다(self) -> CheckedDirectionsOut:
            build(self)  # 규칙을 어기면 ValueError -> 스키마 검사 실패
            return self

    return CheckedDirectionsOut


# ---- 프롬프트 변수 (모두 글자. 캐시 키가 되므로 JSON으로 바꿀 수 있어야 한다) ----
def to_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1)


def _rejection_of(oa: OAResult, unit: JudgmentUnit) -> Rejection:
    for r in oa.rejections:
        if r.no == unit.rejection:
            return r
    raise ValueError(f"판단 단위 {unit.unit_id}의 거절이유 {unit.rejection}이 OA 결과에 없음")


def missing_claim_texts(inp: F4Input, unit: JudgmentUnit) -> list[int]:
    """이 묶음이 쓰는 청구항(함께 읽는 청구항 포함) 중 입력에 글자가 없는 번호."""
    have = {c.claim for c in inp.claims_text}
    return [n for n in [*unit.claims, *unit.read_with] if n not in have]


def unit_variables(
    inp: F4Input, unit: JudgmentUnit, f3: list, bundle: LegalEvidenceBundle, max_candidates: int
) -> dict[str, str]:
    oa, rej = inp.oa, _rejection_of(inp.oa, unit)
    wanted = [*unit.claims, *unit.read_with]
    texts = {c.claim: c.text for c in inp.claims_text}
    claims_text = "\n\n".join(f"[청구항 {n}]\n{texts[n]}" for n in wanted if n in texts)
    return {
        "max_candidates": str(max_candidates),
        "unit": to_json(
            {
                "unit_id": unit.unit_id,
                "rejection": unit.rejection,
                "rejection_kind": unit.rejection_kind.value,
                "representative_claim": unit.representative_claim,
                "claims": unit.claims,
                "read_with": unit.read_with,
            }
        ),
        "rejection": to_json(
            {
                "no": rej.no,
                "kind": rej.kind.value,
                "article": rej.article.value or rej.article.raw_text,
                "claims": rej.claims.value,
                "citations": [
                    {
                        "label": c.label,
                        "number": c.number.value or c.number.raw_text,
                        "cited_paragraphs": c.cited_paragraphs.value,
                    }
                    for c in rej.citations
                ],
                "examiner_reasoning": {
                    "summary": rej.examiner_reasoning.value,
                    "raw_text": rej.examiner_reasoning.raw_text,
                },
            }
        ),
        "oa_context": to_json(
            {
                "notice_kind": oa.notice_kind.value,
                "allowable_claims": oa.examiner_hints.allowable_claims.value,
                "amendment_note": oa.examiner_hints.amendment_note.raw_text,
            }
        ),
        "claims_text": claims_text or "(입력에 청구항 글자가 없음)",
        "comparison": to_json([r.model_dump(mode="json") for r in f3]),
        "legal": to_json(
            {
                "status": bundle.status.model_dump(mode="json"),
                "claims": [c.model_dump(mode="json") for c in bundle.claims],
            }
        ),
    }


def _failed_result(
    unit: JudgmentUnit,
    limit: ExtractedValue[AmendmentLimit],
    evidence: list[Evidence],
    flags: list[Flag],
    error: Exception,
) -> DirectionCandidates:
    """모델 호출이 실패한 묶음의 자리 표시: 후보 0개, 확인되지 않음, 직접 판단 필요."""
    return DirectionCandidates(
        unit_id=unit.unit_id,
        candidates=[],
        selection=None,
        amendment_limit=limit,
        status=failed_status(error),
        evidence=evidence,
        needs_recheck=True,
        recheck_reason=why(error),
        flags=[Flag.NEEDS_HUMAN_JUDGMENT, *(f for f in flags if f != Flag.NEEDS_HUMAN_JUDGMENT)],
    )


def _over_limit_result(
    unit: JudgmentUnit,
    limit: ExtractedValue[AmendmentLimit],
    evidence: list[Evidence],
    flags: list[Flag],
    max_units: int,
    all_ids: list[str],
) -> DirectionCandidates:
    """판단 단위 상한 max_units 밖 묶음의 자리 표시: 호출 없이 limit_reached + 직접 판단 필요."""
    return DirectionCandidates(
        unit_id=unit.unit_id,
        candidates=[],
        selection=None,
        amendment_limit=limit,
        status=Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.LIMIT_REACHED),
        evidence=evidence,
        needs_recheck=True,
        recheck_reason=(
            f"판단 단위 상한 max_units {max_units}에 닿아 다루지 않음 "
            f"(전체 {len(all_ids)}묶음 중 앞 {max_units}묶음만 다룸)"
        ),
        flags=[Flag.NEEDS_HUMAN_JUDGMENT, *(f for f in flags if f != Flag.NEEDS_HUMAN_JUDGMENT)],
    )


# ---- 단계 진입 ----
def build_directions(
    inp: F4Input, ctx: RunContext, *, options: F4Options | None = None
) -> list[DirectionCandidates]:
    """판단 단위마다 DirectionCandidates 하나 (order 순).

    모델은 단위마다 한 번, 출력 검사 실패 때 한 번 더 부른다.

    묶음 하나의 모델 호출 실패(출력 검사 두 번 실패, 전송 오류, 호출 상한)는 그 묶음만 후보 0개
    + 확인되지 않음 + 직접 판단 필요로 남기고 다음 묶음으로 간다 (이유는 recheck_reason).
    시도한 모든 묶음이 실패하면 단계가 못 돈 것이라 예외를 그대로 던진다 (호출 상한은 제외).
    """
    options = options or load_f4_options()
    if not inp.units:
        logger.warning("f4.direction %s: 판단 단위가 0개라 방향 후보를 만들지 않음", inp.oa.oa_id)
        return []
    ids = [u.unit_id for u in inp.units]
    if len(set(ids)) != len(ids):
        raise ValueError(f"판단 단위 unit_id에 중복이 있음: {ids}")
    # 묶음이 상한보다 많으면 앞 max_units개만 모델을 부르고, 넘는 묶음은 부르지 않고 보류한다.
    # 의견서·보정 단계는 이 결과(넘는 묶음은 후보 없음)를 받으므로 같은 묶음 집합을 다룬다.
    ordered = sorted(inp.units, key=lambda u: (u.order, u.unit_id))
    over_ids = {u.unit_id for u in ordered[options.max_units :]}
    if over_ids:
        logger.warning(
            "f4.direction %s: 판단 단위 %d개가 상한 max_units %d를 넘어 %d개는 보류",
            inp.oa.oa_id,
            len(ordered),
            options.max_units,
            len(over_ids),
        )

    limit = amendment_limit_of(inp.oa)
    # 보정 제한 스위치가 켜져 있는데 통지 종류를 모르면: 제한을 짐작하지 않고 확인을 요청한다
    ask_kind = options.final_rejection_limit and limit.value is None
    if ask_kind:
        logger.warning("f4.direction %s: 통지 종류를 몰라 보정 제한 확인 필요", inp.oa.oa_id)
    # 스위치를 껐는데 최후통지면 제한 없이 만든 초안이라는 사실을 확인 사항과 표시로 남긴다
    unlimited_final = not options.final_rejection_limit and limit.value == AmendmentLimit.FINAL
    if unlimited_final:
        logger.warning("f4.direction %s: 최후통지인데 보정 제한을 적용하지 않음", inp.oa.oa_id)
    checks = (
        [NOTICE_KIND_CHECK] if ask_kind else [NOTICE_FINAL_UNLIMITED] if unlimited_final else []
    )
    results: list[DirectionCandidates] = []
    errors: list[Exception] = []  # 호출 실패로 보류한 묶음의 예외 (호출 상한은 담지 않음)
    for unit in ordered:
        f3 = f3_results(inp, unit)
        bundle = legal_bundle_for(inp, unit)
        gaps = f3_gaps(inp, unit, f3)
        status, evidence = _status_of(f3, bundle, unit, gaps.statuses), _evidence_of(f3)
        legal_review = legal_needs_review(bundle)
        review = [Flag.NEEDS_HUMAN_REVIEW] if gaps.needs_review or legal_review else []
        unit_checks = [*checks, *gaps.checks, *([LEGAL_REVIEW_CHECK] if legal_review else [])]
        # 청구항 글자 없이 모델을 부르면 후보가 글자를 못 보고 나온 것이라 사람이 보게 표시한다
        missing = missing_claim_texts(inp, unit)
        if missing:
            logger.warning("f4.direction %s: 청구항 글자가 입력에 없음 %s", unit.unit_id, missing)
        flags = (
            [Flag.NEEDS_HUMAN_REVIEW]
            if missing or ask_kind or unlimited_final or gaps.needs_review or legal_review
            else []
        )

        def build(
            out: DirectionsOut,
            unit=unit,
            status=status,
            evidence=evidence,
            flags=flags,
            unit_checks=unit_checks,
            review=review,
        ):
            return _build(
                out,
                unit,
                inp.oa,
                status,
                evidence,
                limit,
                options.max_candidates,
                flags,
                unit_checks,
                review,
            )

        if unit.unit_id in over_ids:
            # 상한 밖 묶음: 호출 없이 limit_reached 보류 (원문 글자 없이 상한 숫자와 범위만)
            results.append(_over_limit_result(unit, limit, evidence, flags, options.max_units, ids))
            continue
        variables = unit_variables(inp, unit, f3, bundle, options.max_candidates)
        try:
            out = call_with_one_retry(STEP, variables, _checked_schema(build), ctx)
        except BUNDLE_ERRORS as e:
            # 이 묶음만 보류한다: 후보 없이 확인되지 않음 + 이유, 사람이 직접 판단한다
            logger.warning("f4.direction %s: %s (이 묶음만 보류)", unit.unit_id, why(e))
            results.append(_failed_result(unit, limit, evidence, flags, e))
            if not is_limit(e):
                errors.append(e)
            continue
        result = build(out)
        if not result.candidates:
            logger.warning(
                "f4.direction %s: 모델이 후보를 0개 냄 (확인되지 않음, 직접 판단 필요)",
                unit.unit_id,
            )
        results.append(result)
    raise_if_all_failed(STEP, len(ordered) - len(over_ids), errors)
    return results
