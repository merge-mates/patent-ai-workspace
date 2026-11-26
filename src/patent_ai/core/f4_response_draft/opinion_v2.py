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
import re

from pydantic import BaseModel, ConfigDict, Field, model_validator

from patent_ai.core.bundle_errors import BUNDLE_ERRORS, failed_status, why
from patent_ai.core.f4_response_draft.directions import (
    _rejection_of,
    f3_results,
    to_json,
    unit_scope,
    unit_variables,
)
from patent_ai.core.f4_response_draft.inputs import ExternalAmendment, F4Input, legal_bundle_for
from patent_ai.core.f4_response_draft.llm_call import MAX_ERROR_CHARS, RETRY_NOTE
from patent_ai.core.f4_response_draft.opinion import (
    SECTION_TITLES,
    OpinionPart,
    has_amendment,
    selected_candidate,
)
from patent_ai.core.llm.client import call_model
from patent_ai.core.llm.errors import ModelOutputInvalid
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
    """묶음 하나의 반박 (대응과 근거) + 변리사가 확인할 점(본문과 따로)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    response: str
    checks: list[str] = Field(default_factory=list)


class CaseOut(BaseModel):
    """사건 전체 칸: 지적 요지, 보정 설명(보정이 없으면 null), 마무리 + 확인할 점."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    points: str
    amendment: str | None
    closing: str
    checks: list[str] = Field(default_factory=list)


# 제출할 글에 들어가면 안 되는 것: 입력 자료의 영어 키·코드 값과 검토 표시.
# 있으면 출력 검사에 떨어뜨려 한 번 다시 부른다 (확인할 점은 checks 칸에 따로 쓰게 한다)
_INTERNAL = re.compile(
    r"\b(supported|initial|final|merged_into|changed_in_other_units|unit_id|notice_kind|"
    r"amended|deleted|added|unchanged|clarity|inventive_step|novelty|difference_candidate|"
    r"disclosed|not_found_in_scope|unverified|confirmed|ai_found)\b"
    r"|\[(법률 근거 )?확인 필요[^\]]*\]|조문 표기",
    re.IGNORECASE,
)
_MARK = re.compile(r"\s*\[(법률 근거 )?확인 필요[^\]]*\]")


def internal_words(text: str | None) -> list[str]:
    """글에 섞인 내부 말 (중복 없이, 나온 순서)."""
    return list(dict.fromkeys(m.group(0) for m in _INTERNAL.finditer(text or "")))


def _strip_marks(text: str) -> str:
    """다시 불러도 남은 검토 표시만 지운다 (글은 살린다). 남은 코드 값은 경고로만 남긴다."""
    cleaned = _MARK.sub("", text)
    if left := internal_words(cleaned):
        logger.warning("f4.opinion: 다시 불러도 글에 내부 말이 남음: %s", left)
    return cleaned


def _checked_unit(strict: bool = True) -> type[UnitOut]:
    class CheckedUnitOut(UnitOut):
        @model_validator(mode="after")
        def _반박이_비지_않는다(self) -> CheckedUnitOut:
            if not self.response.strip():
                raise ValueError("response(대응과 근거)가 비어 있음")
            if strict and (found := internal_words(self.response)):
                raise ValueError(
                    f"response에 입력 키·코드 값이나 검토 표시가 들어감: {found}. "
                    "한국어 특허 실무 말로 풀어 쓰고, 확인할 점은 checks에 따로 적을 것"
                )
            return self

    return CheckedUnitOut


def _checked_case(amended: bool, strict: bool = True) -> type[CaseOut]:
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
            text = " ".join(x for x in (self.points, self.amendment, self.closing) if x)
            if strict and (found := internal_words(text)):
                raise ValueError(
                    f"글에 입력 키·코드 값이나 검토 표시가 들어감: {found}. "
                    "한국어 특허 실무 말로 풀어 쓰고, 확인할 점은 checks에 따로 적을 것"
                )
            return self

    return CheckedCaseOut


def _call_clean[T: BaseModel](
    step: str, variables: dict[str, str], strict: type[T], lenient: type[T], ctx: RunContext
) -> T:
    """첫 답은 내부 말 검사까지(strict). 떨어지면 오류를 붙여 한 번 더 부르고,
    그 답은 내부 말 검사 없이(lenient) 받는다.

    두 번째에도 내부 말이 남으면 묶음을 보류하지 않고 표시만 지운다(_strip_marks).
    다른 검사(빈 칸·보정 설명 유무)는 두 번째에도 그대로라 떨어지면 지금처럼 그 묶음만 보류된다.
    """
    try:
        first = call_model(step, {**variables, "retry_note": ""}, strict, ctx=ctx, attempt=1)
        return first.parsed  # type: ignore[return-value]
    except ModelOutputInvalid as e:
        error = str(e)[:MAX_ERROR_CHARS]
        logger.warning("%s: 모델 답이 검사에 떨어져 검사 오류를 붙여 한 번 더 부름", step)
    retry = {**variables, "retry_note": RETRY_NOTE.format(error=error)}
    second = call_model(step, retry, lenient, ctx=ctx, attempt=2)
    return second.parsed  # type: ignore[return-value]


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
    # 모델이 키 이름·코드 값을 글에 옮겨 쓰지 않게 키와 값을 한국어로 준다
    for c in sorted(_changed(ext), key=lambda c: c.claim):
        merged = {"합친 곳": _claims_ko(c.merged_into)} if c.merged_into else {}
        kind = CHANGE_KO.get(c.change, c.change)
        if wanted is not None and c.claim not in wanted:
            others.append({"항": c.claim, "바뀜": kind, **merged})
            continue
        rows.append(
            {
                "항": c.claim,
                "바뀜": kind,
                "보정 전": c.before if c.before is not None else before.get(c.claim),
                "보정 후": c.after,
                **merged,
            }
        )
    changed = {c.claim for c in _changed(ext)}
    scope = sorted(wanted) if wanted is not None else sorted(before)
    data = {
        "출처": ext.source,
        "바뀐 항": rows,
        "바뀌지 않은 항": [n for n in scope if n not in changed],
    }
    if wanted is not None:
        # 범위 밖 보정 항을 모델이 "보정 결과에 없다"고 쓰지 않게
        # → 다른 묶음에서 다루는 항으로 알린다
        data["다른 묶음에서 바뀐 항"] = others
    return to_json(data)


def _without_unit_id(data):
    """대비 결과 안의 묶음 ID(unit_id)를 모든 깊이에서 뺀다."""
    if isinstance(data, dict):
        return {k: _without_unit_id(v) for k, v in data.items() if k != "unit_id"}
    if isinstance(data, list):
        return [_without_unit_id(v) for v in data]
    return data


def _claims_ko(claims: list[int]) -> str:
    return ", ".join(f"제{n}항" for n in claims)


def _same_as_ko(target: str) -> str:
    """같은 취지 값("claim:3", "rejection:1") → 글자."""
    kind, _, number = target.partition(":")
    return (
        f"청구항 {number}"
        if kind == "claim"
        else f"거절이유 {number}"
        if kind == "rejection"
        else target
    )


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
            "항": r.claim,
            "거절이유": r.rejection,
            "인용": r.citations,
            "인용 위치": r.locations,
            "같은 취지": [_same_as_ko(x) for x in r.same_as],
            "심사관 원문": r.raw_text,
        }
        if r.clarity_terms:
            row["지적 표현"] = r.clarity_terms
        if not confirmed:
            # 내부 사유 코드(ambiguous 등)는 넣지 않는다: 모델이 글에 옮겨 쓴다
            row["상태"] = "통지서 원문과 대조하지 못함 (이 줄을 쓰면 checks에 확인할 점을 적는다)"
        rows.append(row)
    rows.sort(key=lambda x: (x["항"], x["거절이유"] or 0))
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
        "unit": to_json(
            {
                "거절이유": unit.rejection,
                "종류": KIND_KO.get(unit.rejection_kind.value, unit.rejection_kind.value),
                "대표 청구항": unit.representative_claim,
                "청구항": unit.claims,
                "함께 읽을 청구항": unit.read_with,
            }
        ),
        "rejection": _rejection_ko(_rejection_of(inp.oa, unit)),
        "oa_context": _oa_context_ko(inp),
        "claims_text": base["claims_text"],
        # 묶음 ID(unit_id)는 모델이 글에 옮겨 써서 뺀다 (나머지 코드 값은 출력 검사가 잡는다)
        "comparison": to_json([_without_unit_id(r.model_dump(mode="json")) for r in f3]),
        "legal": base["legal"],
        "examiner_rows": examiner_rows_v2(inp, unit),
        "rebuttal": _rebuttal_of(chosen),
        "amendment": amendment_rows(inp, sorted(set(scope) | set(unit.claims))),
    }


FAILED_AMENDMENT = "(보정 설명 생성 실패: 직접 작성)"
NOTICE_KO = {
    "initial": "최초거절이유통지",
    "final": "최후거절이유통지",
    "unknown": "통지 종류 모름",
}


def _article_ko(code: str | None) -> str | None:
    """조문 코드("29-2", "42-4-2") → "특허법 제29조제2항". 모양이 다르면 그대로."""
    if not code or not re.fullmatch(r"\d+(-\d+){0,2}", code):
        return code
    jo, *rest = code.split("-")
    tail = "".join(f"제{n}{u}" for n, u in zip(rest, ("항", "호"), strict=False))
    return f"특허법 제{jo}조{tail}"


def _rejection_ko(rej) -> str:
    return to_json(
        {
            "번호": rej.no,
            "종류": KIND_KO.get(rej.kind.value, rej.kind.value),
            "조문": _article_ko(rej.article.value) or rej.article.raw_text,
            "대상 청구항": rej.claims.value,
            "인용문헌": [
                {
                    "라벨": c.label,
                    "번호": c.number.value or c.number.raw_text,
                    "인용 문단": c.cited_paragraphs.value,
                }
                for c in rej.citations
            ],
            "심사관 판단": {
                "요지": rej.examiner_reasoning.value,
                "원문": rej.examiner_reasoning.raw_text,
            },
        }
    )


def _oa_context_ko(inp: F4Input) -> str:
    oa = inp.oa
    return to_json(
        {
            "통지 종류": NOTICE_KO.get(oa.notice_kind.value, oa.notice_kind.value),
            "특허 가능한 청구항": oa.examiner_hints.allowable_claims.value,
            "보정 참고사항": oa.examiner_hints.amendment_note.raw_text,
        }
    )


def _case_info(inp: F4Input) -> str:
    oa = inp.oa

    def show(v) -> str:
        return v.raw_text if v.raw_text else "(통지서에서 확인 필요)"

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
                    "번호": r.no,
                    "종류": KIND_KO.get(r.kind.value, r.kind.value),
                    "조문": _article_ko(r.article.value) or r.article.raw_text,
                    "대상 청구항": r.claims.value,
                    "이 초안": "다룸" if r.supported else "다루지 않음 (직접 검토 필요)",
                    "심사관 판단": r.examiner_reasoning.value,
                }
                for r in oa.rejections
            ]
        ),
        "units": to_json([{"거절이유": u.rejection, "청구항": u.claims} for u in units]),
        "amendment": amendment_rows(inp),
        "oa_context": _oa_context_ko(inp),
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
    checks: list[str] = []
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
            out = _call_clean(
                STEP_UNIT,
                _unit_variables(inp, unit, chosen, f3, bundle),
                _checked_unit(),
                _checked_unit(strict=False),
                ctx,
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
        responses.append(f"{title}\n{_strip_marks(out.response)}")
        # 확인할 점은 본문과 따로 모은다 (어느 묶음 것인지 앞에 붙임)
        claims_head = f"청구항 {', '.join(map(str, unit.claims))}"
        checks += [f"[{claims_head}] {c.strip()}" for c in out.checks if c.strip()]
        based_on.append(BasedOn(unit_id=unit.unit_id, candidate_id=chosen.candidate_id))
        statuses += [chosen.status, bundle.status]
        legal_unverified = legal_unverified or bundle.status.value != StatusValue.CONFIRMED
        evidence += [e for e in chosen.evidence if e not in evidence]

    sections: list[OpinionSection] = []
    if responses:
        amended = bool(ext_changed)
        try:
            case = _call_clean(
                STEP_CASE,
                _case_variables(inp, list(inp.units)),
                _checked_case(amended),
                _checked_case(amended, strict=False),
                ctx,
            )
        except BUNDLE_ERRORS as e:
            # 사건 칸이 실패해도 반박은 살린다: 요지·마무리 자리는 확인 필요로 둔다
            logger.warning("f4.opinion_case %s: %s (요지·마무리는 비움)", inp.oa.oa_id, why(e))
            failed_statuses.append(failed_status(e))
            case = CaseOut(
                points="(지적 요지 생성 실패: 직접 작성)",
                amendment=None,
                closing="(마무리 생성 실패: 직접 작성)",
            )
        texts = {
            OpinionKey.CASE_INFO: _case_info(inp),
            OpinionKey.POINTS: _strip_marks(case.points),
            OpinionKey.RESPONSE: "\n\n".join(responses),
            OpinionKey.AMENDMENT: (
                f"{_strip_marks(case.amendment) if case.amendment else FAILED_AMENDMENT}"
                f"\n\n{amendment_table(inp)}"
                if amended
                else None
            ),
            OpinionKey.CLOSING: _strip_marks(case.closing),
            # 변리사 확인 사항: 제출할 본문과 따로 맨 끝 칸 (없으면 칸을 만들지 않음)
            OpinionKey.REVIEW: (
                "\n".join(
                    f"- {c}" for c in [*checks, *(x.strip() for x in case.checks if x.strip())]
                )
                or None
            ),
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
