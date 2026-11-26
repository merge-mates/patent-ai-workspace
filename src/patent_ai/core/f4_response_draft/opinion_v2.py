"""의견서만 (설정 amendment_enabled: false, 11/26 골 모드 P5): 바깥 보정 결과로 의견서를 쓴다.

보정안은 만들지 않는다 (은진 담당). 보정 결과는 F4Input.external_amendment로 받는다.
구조 (실제 의견서 "거절이유 요약 → 보정 → 거절이유별 검토 → 결론"):
- 묶음마다 모델 1회 (f4.opinion_unit): 대응과 근거(반박)만. 고른 방향에서는 반박 논점만 쓰고
  보정 내용은 바깥 보정 결과를 따른다 (D2-1).
- 사건 전체 모델 1회 (f4.opinion_case): 지적 요지·보정 설명·마무리. 사건 정보와 보정 결과 표는 코드.
- 보정 설명 칸 유무는 바깥 보정 결과로 정한다. 고른 방향의 보정 유무와 어긋난 묶음은
  mismatch_units에 남긴다 (출력 검사 실패로 보류하지 않는다).
"""

import logging

from pydantic import BaseModel, ConfigDict, model_validator

from patent_ai.core.bundle_errors import BUNDLE_ERRORS, failed_status, why
from patent_ai.core.f4_response_draft.directions import (
    _rejection_of,
    f3_results,
    to_json,
    unit_scope,
    unit_variables,
)
from patent_ai.core.f4_response_draft.inputs import ExternalAmendment, F4Input, legal_bundle_for
from patent_ai.core.f4_response_draft.llm_call import call_with_one_retry
from patent_ai.core.f4_response_draft.opinion import (
    SECTION_TITLES,
    OpinionPart,
    has_amendment,
    selected_candidate,
)
from patent_ai.core.llm.limits import RunContext
from patent_ai.core.schemas.common import Evidence, Flag, Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.direction import DirectionCandidates
from patent_ai.core.schemas.drafts import BasedOn, OpinionKey, OpinionSection
from patent_ai.core.schemas.judgment_unit import JudgmentUnit
from patent_ai.core.schemas.propagation import propagate

logger = logging.getLogger(__name__)

STEP_UNIT = "f4.opinion_unit"
STEP_CASE = "f4.opinion_case"
NO_AMENDMENT = "(보정 결과 없음: OA 당시 청구항 그대로 반박한다)"
CHANGE_KO = {"amended": "보정", "deleted": "삭제", "added": "신설"}
# 거절이유 종류 코드 → 의견서 글자
KIND_KO = {"inventive_step": "진보성", "novelty": "신규성", "clarity": "명확성", "other": "기타"}


class UnitOut(BaseModel):
    """묶음 하나의 반박 (대응과 근거)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    response: str


class CaseOut(BaseModel):
    """사건 전체 칸: 지적 요지, 보정 설명(보정이 없으면 null), 마무리."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    points: str
    amendment: str | None
    closing: str


def _checked_unit() -> type[UnitOut]:
    class CheckedUnitOut(UnitOut):
        @model_validator(mode="after")
        def _반박이_비지_않는다(self) -> CheckedUnitOut:
            if not self.response.strip():
                raise ValueError("response(대응과 근거)가 비어 있음")
            return self

    return CheckedUnitOut


def _checked_case(amended: bool) -> type[CaseOut]:
    """보정 설명 유무는 바깥 보정 결과로 정한다 (D2-1).

    어긋나면 출력 검사 실패 -> 한 번 다시 부름.
    """

    class CheckedCaseOut(CaseOut):
        @model_validator(mode="after")
        def _칸이_보정_결과와_맞는다(self) -> CheckedCaseOut:
            if not self.points.strip() or not self.closing.strip():
                raise ValueError("points·closing은 비울 수 없음")
            if amended and not (self.amendment or "").strip():
                raise ValueError("보정 결과에 바뀐 항이 있는데 amendment(보정 설명)가 비어 있음")
            if not amended and self.amendment is not None:
                raise ValueError("보정 결과가 없으면 amendment는 null이어야 함")
            return self

    return CheckedCaseOut


def _changed(ext: ExternalAmendment | None) -> list:
    return [c for c in (ext.claims if ext else []) if c.change != "unchanged"]


def amendment_rows(inp: F4Input, claims: list[int] | None = None) -> str:
    """바깥 보정 결과 (claims가 있으면 그 항만).

    항마다 바뀜 종류·보정 앞뒤 글자. 그대로인 항은 번호만.
    """
    ext = inp.external_amendment
    if ext is None or not _changed(ext):
        return NO_AMENDMENT
    before = {c.claim: c.text for c in inp.claims_text}
    wanted = set(claims) if claims is not None else None
    rows = []
    others = []  # 이 묶음 범위 밖에서 바뀐 항 (번호·종류만)
    for c in sorted(_changed(ext), key=lambda c: c.claim):
        merged = {"merged_into": c.merged_into} if c.merged_into else {}
        if wanted is not None and c.claim not in wanted:
            others.append({"claim": c.claim, "change": c.change, **merged})
            continue
        rows.append(
            {
                "claim": c.claim,
                "change": c.change,
                "before": c.before if c.before is not None else before.get(c.claim),
                "after": c.after,
                **merged,
            }
        )
    changed = {c.claim for c in _changed(ext)}
    scope = sorted(wanted) if wanted is not None else sorted(before)
    data = {
        "source": ext.source,
        "changed": rows,
        "unchanged": [n for n in scope if n not in changed],
    }
    if wanted is not None:
        # 범위 밖 보정 항을 모델이 "보정 결과에 없다"고 쓰지 않게
        # → 다른 묶음에서 다루는 항으로 알린다
        data["changed_in_other_units"] = others
    return to_json(data)


def examiner_rows_v2(inp: F4Input, unit: JudgmentUnit) -> str:
    """보정 범위 청구항마다 심사관이 든 인용·위치. 확인된 줄 + 원문 대조에 떨어졌지만 모델 값이
    남은 줄(D3, "확인 필요" 표시). 값이 없는 빈 줄은 싣지 않는다."""
    scope = set(unit_scope(inp, unit).claims) | set(unit.claims)
    rows = []
    for r in inp.oa.claim_rows:
        if r.claim not in scope:
            continue
        confirmed = r.status.value == StatusValue.CONFIRMED
        has_value = bool(r.citations or r.locations or r.raw_text)
        # 값이 없는 빈 줄만 뺀다. 원문 대조 실패(check_failed)뿐 아니라 모델이 애매 표시를 붙인 줄도
        # 값이 있으면 "확인 필요"로 싣는다 (빠지면 모델이 "심사관이 위치를 특정 안 했다"고 단정함)
        if not confirmed and not has_value:
            continue
        row = {
            "claim": r.claim,
            "rejection": r.rejection,
            "citations": r.citations,
            "locations": r.locations,
            "same_as": r.same_as,
            "examiner_text": r.raw_text,
        }
        if r.clarity_terms:
            row["clarity_terms"] = r.clarity_terms
        if not confirmed:
            reason = r.status.reason.value if r.status.reason else "미확인"
            why_not = r.check_failed or f"모델 표시: {reason}"
            row["status"] = f"확인 필요 ({why_not})"
        rows.append(row)
    rows.sort(key=lambda x: (x["claim"], x["rejection"] or 0))
    if not rows:
        logger.warning("f4.opinion_unit %s: 항별 심사관 근거가 0개", unit.unit_id)
        return "(항별 심사관 근거 없음: 거절이유 단위 자료만 있음)"
    return to_json(rows)


def _rebuttal_of(chosen) -> str:
    """고른 방향에서 반박 논점만 (보정 종류 amendment_core는 바깥 보정 결과를 따르므로 뺀다)."""
    data = chosen.model_dump(
        mode="json", include={"coarse", "name", "reason", "per_rejection", "rebuttal"}
    )
    if not chosen.rebuttal and not chosen.per_rejection:
        data["note"] = (
            "이 방향에는 반박 논점이 없음: 대비 결과의 차이점과 항별 심사관 근거로 반박을 세운다"
        )
    return to_json(data)


def _unit_variables(inp: F4Input, unit: JudgmentUnit, chosen, f3, bundle) -> dict[str, str]:
    base = unit_variables(inp, unit, f3, bundle, max_candidates=1)
    scope = unit_scope(inp, unit).claims
    return {
        "unit": base["unit"],
        "rejection": base["rejection"],
        "oa_context": base["oa_context"],
        "claims_text": base["claims_text"],
        "comparison": base["comparison"],
        "legal": base["legal"],
        "examiner_rows": examiner_rows_v2(inp, unit),
        "rebuttal": _rebuttal_of(chosen),
        "amendment": amendment_rows(inp, sorted(set(scope) | set(unit.claims))),
    }


def _case_info(inp: F4Input) -> str:
    oa = inp.oa

    def show(v) -> str:
        return v.raw_text if v.raw_text else "[확인 필요]"

    return (
        f"출원번호: {show(oa.application_number)}\n"
        f"통지서 발송번호: {show(oa.dispatch_number)}\n"
        f"통지일: {show(oa.notice_date)}\n"
        f"제출기한: {show(oa.response_due)}"
    )


def amendment_table(inp: F4Input) -> str:
    """보정 결과 표 (코드가 만든다): 바뀐·지운·새 항 번호와 종류."""
    lines = ["[보정 결과 표]"]
    for c in sorted(_changed(inp.external_amendment), key=lambda c: c.claim):
        into = ""
        if c.merged_into:
            into = f" ({', '.join(f'제{n}항' for n in c.merged_into)}에 합침)"
        lines.append(f"- 제{c.claim}항: {CHANGE_KO.get(c.change, c.change)}{into}")
    return "\n".join(lines)


def _case_variables(inp: F4Input, units: list[JudgmentUnit]) -> dict[str, str]:
    oa = inp.oa
    return {
        "rejections": to_json(
            [
                {
                    "no": r.no,
                    "kind": r.kind.value,
                    "article": r.article.value or r.article.raw_text,
                    "claims": r.claims.value,
                    "supported": r.supported,
                    "examiner_reasoning": r.examiner_reasoning.value,
                }
                for r in oa.rejections
            ]
        ),
        "units": to_json(
            [{"unit_id": u.unit_id, "rejection": u.rejection, "claims": u.claims} for u in units]
        ),
        "amendment": amendment_rows(inp),
        "oa_context": to_json(
            {
                "notice_kind": oa.notice_kind.value,
                "allowable_claims": oa.examiner_hints.allowable_claims.value,
                "amendment_note": oa.examiner_hints.amendment_note.raw_text,
            }
        ),
    }


def build_opinion_v2(
    inp: F4Input, directions: list[DirectionCandidates], ctx: RunContext
) -> OpinionPart:
    """묶음마다 반박, 사건 전체 한 번 요약·보정 설명·마무리. 묶음 실패는 그 묶음만 보류."""
    by_unit = {d.unit_id: d for d in directions}
    missing = [u.unit_id for u in inp.units if u.unit_id not in by_unit]
    if missing:
        raise ValueError(f"방향 후보 결과가 없는 판단 단위: {missing}")
    ext_changed = {c.claim for c in _changed(inp.external_amendment)}
    responses: list[str] = []
    based_on: list[BasedOn] = []
    held: list[str] = []
    mismatch: list[str] = []
    failed_reasons: dict[str, str] = {}
    failed_statuses: list[Status] = []
    statuses: list[Status] = []
    evidence: list[Evidence] = []
    legal_unverified = False
    for unit in sorted(inp.units, key=lambda u: (u.order, u.unit_id)):
        chosen = selected_candidate(by_unit[unit.unit_id])
        if chosen is None:
            logger.warning("f4.opinion_unit %s: 고른 방향이 없어 이 묶음은 보류", unit.unit_id)
            held.append(unit.unit_id)
            continue
        scope = set(unit_scope(inp, unit).claims) | set(unit.claims)
        if has_amendment(chosen) != bool(scope & ext_changed):
            mismatch.append(unit.unit_id)  # 방향 품질은 이번 범위 밖: 표시만 남긴다
        f3, bundle = f3_results(inp, unit), legal_bundle_for(inp, unit)
        try:
            out = call_with_one_retry(
                STEP_UNIT, _unit_variables(inp, unit, chosen, f3, bundle), _checked_unit(), ctx
            )
        except BUNDLE_ERRORS as e:
            logger.warning("f4.opinion_unit %s: %s (이 묶음만 보류)", unit.unit_id, why(e))
            held.append(unit.unit_id)
            failed_reasons[unit.unit_id] = why(e)
            failed_statuses.append(failed_status(e))
            continue
        rej = _rejection_of(inp.oa, unit)
        # 의견서에 들어가는 글이라 거절이유 종류를 한국어로 (전에는 clarity 같은 코드 값이 나갔다)
        kind = KIND_KO.get(rej.kind.value, rej.kind.value)
        title = f"[거절이유 {rej.no} ({kind}) · 청구항 {', '.join(map(str, unit.claims))}]"
        responses.append(f"{title}\n{out.response}")
        based_on.append(BasedOn(unit_id=unit.unit_id, candidate_id=chosen.candidate_id))
        statuses += [chosen.status, bundle.status]
        legal_unverified = legal_unverified or bundle.status.value != StatusValue.CONFIRMED
        evidence += [e for e in chosen.evidence if e not in evidence]

    sections: list[OpinionSection] = []
    if responses:
        amended = bool(ext_changed)
        try:
            case = call_with_one_retry(
                STEP_CASE, _case_variables(inp, list(inp.units)), _checked_case(amended), ctx
            )
        except BUNDLE_ERRORS as e:
            # 사건 칸이 실패해도 반박은 살린다: 요지·마무리 자리는 확인 필요로 둔다
            logger.warning("f4.opinion_case %s: %s (요지·마무리는 비움)", inp.oa.oa_id, why(e))
            failed_statuses.append(failed_status(e))
            case = CaseOut(
                points="[확인 필요: 지적 요지 생성 실패]", amendment=None, closing="[확인 필요]"
            )
        texts = {
            OpinionKey.CASE_INFO: _case_info(inp),
            OpinionKey.POINTS: case.points,
            OpinionKey.RESPONSE: "\n\n".join(responses),
            OpinionKey.AMENDMENT: (
                f"{case.amendment or '[확인 필요: 보정 설명 생성 실패]'}\n\n{amendment_table(inp)}"
                if amended
                else None
            ),
            OpinionKey.CLOSING: case.closing,
        }
        sections = [
            OpinionSection(key=k, title=SECTION_TITLES[k], ai_text=t)
            for k, t in texts.items()
            if t is not None
        ]
    flags: list[Flag] = []
    if held:
        flags.append(Flag.NEEDS_HUMAN_JUDGMENT)
    if legal_unverified:
        flags.append(Flag.NEEDS_HUMAN_REVIEW)
    status = (
        propagate(statuses)
        if statuses
        else Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
    )
    return OpinionPart(
        sections=sections,
        based_on=based_on,
        held_units=held,
        failed_reasons=failed_reasons,
        failed_statuses=failed_statuses,
        status=status,
        evidence=evidence,
        flags=flags,
        mismatch_units=mismatch,
    )
