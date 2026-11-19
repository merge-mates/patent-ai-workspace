"""상태 전파와 검토할 사항 모으기. 규칙은 docs/data-model.md 3절 규칙 1·2."""

import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict

from patent_ai.core.schemas.case_materials import CaseMaterials
from patent_ai.core.schemas.common import (
    ExtractedValue,
    Flag,
    ResultBase,
    Status,
    StatusValue,
    UnverifiedReason,
)
from patent_ai.core.schemas.oa_result import Citation, OAResult, Rejection

logger = logging.getLogger(__name__)


def propagate(depends_on: list[Status]) -> Status:
    """기대는 입력의 status로 이 결과의 status를 정한다.

    입력이 모두 confirmed여야 confirmed. 하나라도 아니면 unverified(input_unverified).
    기대는 입력이 없으면 영향 없음으로 보고 confirmed.
    """
    if all(s.value == StatusValue.CONFIRMED for s in depends_on):
        return Status(
            value=StatusValue.CONFIRMED,
            checked=f"기대는 입력 {len(depends_on)}개 확인됨",
        )
    return Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.INPUT_UNVERIFIED)


def mark_recheck[R: ResultBase](result: R, reason: str) -> R:
    """다시 확인할 표시를 단 새 결과를 돌려준다. status는 그대로, 원본도 그대로."""
    return result.model_copy(update={"needs_recheck": True, "recheck_reason": reason})


ReviewKind = Literal[
    "unverified",
    "conflict",
    "needs_recheck",
    "needs_human_judgment",
    "needs_human_review",
    "missing_material",
]


class ReviewItem(BaseModel):
    """사람이 봐야 할 것 하나."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ReviewKind
    # 결과 안 경로. 예: oa_result[0].rejections[0].citations[1].country, materials.missing[0]
    target: str
    label: str  # 사람이 읽는 이름. 예: 조문 "42-3", 인용문헌 번호, 빠진 자료 이름
    reason: str  # 왜. 예: not_extracted, "지원 안 하는 거절이유 42-3"


def _text(v: ExtractedValue) -> str:
    """칸의 사람이 읽는 글자: 값이 있으면 값, 없으면 원문 글자."""
    if v.value is not None:
        return str(v.value)
    return v.raw_text or "알 수 없음"


def _field_item(v: ExtractedValue, target: str, label: str) -> list[ReviewItem]:
    """필드(ExtractedValue) 하나: unverified·conflict면 그 필드 경로에서 한 줄."""
    if v.status.value == StatusValue.UNVERIFIED:
        return [
            ReviewItem(kind="unverified", target=target, label=label, reason=str(v.status.reason))
        ]
    if v.status.value == StatusValue.CONFLICT:
        return [ReviewItem(kind="conflict", target=target, label=label, reason="값이 서로 충돌")]
    return []


def _flag_items(flags: list[Flag], target: str, label: str, flag_reason: dict) -> list[ReviewItem]:
    return [
        ReviewItem(
            kind=f.value,
            target=target,
            label=label,
            reason=flag_reason.get(
                f, "직접 판단 필요" if f == Flag.NEEDS_HUMAN_JUDGMENT else "직접 검토 필요"
            ),
        )
        for f in flags
    ]


def _recheck_items(r: ResultBase, target: str, label: str) -> list[ReviewItem]:
    if not r.needs_recheck:
        return []
    return [
        ReviewItem(kind="needs_recheck", target=target, label=label, reason=r.recheck_reason or "")
    ]


def _items_of_citation(c: Citation, target: str) -> list[ReviewItem]:
    label = _text(c.number)
    items = _field_item(c.number, f"{target}.number", label)
    items += _field_item(c.country, f"{target}.country", label)
    items += _field_item(c.cited_paragraphs, f"{target}.cited_paragraphs", label)
    if c.country.value is None:
        why = f"나라를 못 정함 ({c.country.raw_text or '원문 글자 없음'})"
    else:
        why = f"지원 안 하는 나라 {c.country.value}"
    return items + _flag_items(c.flags, target, label, {Flag.NEEDS_HUMAN_REVIEW: why})


def _items_of_rejection(rej: Rejection, target: str) -> list[ReviewItem]:
    label = _text(rej.article)
    items: list[ReviewItem] = []
    # 지원 안 하는 거절이유 안의 필드도 한 줄씩 낸다 (결과 status에서는 빠지지만 사람은 봐야 함)
    for name in ("article", "claims", "examiner_reasoning"):
        items += _field_item(getattr(rej, name), f"{target}.{name}", label)
    items += _recheck_items(rej, target, label)
    why = {Flag.NEEDS_HUMAN_REVIEW: f"지원 안 하는 거절이유 {label}"} if not rej.supported else {}
    items += _flag_items(rej.flags, target, label, why)
    for j, c in enumerate(rej.citations):
        items += _items_of_citation(c, f"{target}.citations[{j}]")
    return items


def _items_of_oa_result(oa: OAResult, target: str) -> list[ReviewItem]:
    """OAResult 하나: 결과 단위 status 줄은 없이, 확인되지 않은 필드마다 한 줄."""
    items: list[ReviewItem] = []
    named = [
        "application_number",
        "dispatch_number",
        "notice_date",
        "response_due",
        "notice_kind",
        "examined_claim_version",
    ]
    for name in named:
        v = getattr(oa, name)
        if v is not None:
            items += _field_item(v, f"{target}.{name}", oa.oa_id)
    for name in ("allowable_claims", "amendment_note"):
        items += _field_item(
            getattr(oa.examiner_hints, name), f"{target}.examiner_hints.{name}", oa.oa_id
        )
    items += _recheck_items(oa, target, oa.oa_id)
    items += _flag_items(oa.flags, target, oa.oa_id, {})
    for i, rej in enumerate(oa.rejections):
        items += _items_of_rejection(rej, f"{target}.rejections[{i}]")
    return items


def collect_review_items(results: list[ResultBase], materials: CaseMaterials) -> list[ReviewItem]:
    """결과들과 빠진 자료에서 검토할 사항을 모은다.

    OAResult는 필드까지 내려가 확인되지 않은 필드마다 한 줄(경로는 늘 `oa_result[i]...`).
    필드를 모르는 일반 결과는 결과 status 한 줄. 조회 범위 내 없음은 정상 답이라 넣지 않는다.
    결과가 0개여도 빠진 자료 줄은 낸다 (경고는 남김).
    """
    if not results:
        logger.warning("collect_review_items: 결과가 0개")

    items: list[ReviewItem] = []
    for i, r in enumerate(results):
        if isinstance(r, OAResult):
            items += _items_of_oa_result(r, f"oa_result[{i}]")
            continue
        target, label = f"results[{i}]", type(r).__name__
        if r.status.value == StatusValue.UNVERIFIED:
            reason = str(r.status.reason)
            items.append(ReviewItem(kind="unverified", target=target, label=label, reason=reason))
        elif r.status.value == StatusValue.CONFLICT:
            items.append(
                ReviewItem(kind="conflict", target=target, label=label, reason="값이 서로 충돌")
            )
        items += _recheck_items(r, target, label)
        items += _flag_items(r.flags, target, label, {})
    for i, m in enumerate(materials.missing):
        items.append(
            ReviewItem(
                kind="missing_material",
                target=f"materials.missing[{i}]",
                label=m.what,
                reason=str(m.lookup_result),
            )
        )
    return items
