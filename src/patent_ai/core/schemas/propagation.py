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
from patent_ai.core.schemas.oa_result import OAResult, Rejection

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

    model_config = ConfigDict(frozen=True)

    kind: ReviewKind
    target: str  # 결과 안 경로. 예: oa_result.rejections[0].citations[1], materials.missing[0]
    label: str  # 사람이 읽는 이름. 예: 조문 "42-3", 인용문헌 번호, 빠진 자료 이름
    reason: str  # 왜. 예: body_missing, "지원 안 하는 거절이유 42-3"


def _text(v: ExtractedValue) -> str:
    """칸의 사람이 읽는 글자: 값이 있으면 값, 없으면 원문 글자."""
    if v.value is not None:
        return str(v.value)
    return v.raw_text or "알 수 없음"


def _items_of_result(
    r: ResultBase, target: str, label: str, flag_reason: dict, skip_status: bool = False
) -> list[ReviewItem]:
    """결과 하나(ResultBase 칸)에서 나오는 항목: status, 다시 확인, 직접 판단·검토 표시."""
    items: list[ReviewItem] = []
    # skip_status: 안쪽 자식에서 이미 같은 원인 줄이 나왔으면 위에서 다시 세지 않는다
    if skip_status:
        pass
    elif r.status.value == StatusValue.UNVERIFIED:
        items.append(
            ReviewItem(kind="unverified", target=target, label=label, reason=str(r.status.reason))
        )
    elif r.status.value == StatusValue.CONFLICT:
        items.append(
            ReviewItem(kind="conflict", target=target, label=label, reason="값이 서로 충돌")
        )
    if r.needs_recheck:
        items.append(
            ReviewItem(
                kind="needs_recheck", target=target, label=label, reason=r.recheck_reason or ""
            )
        )
    items += _flag_items(r.flags, target, label, flag_reason)
    return items


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


def _status_lines(items: list[ReviewItem]) -> bool:
    """이 항목들 안에 unverified·conflict 줄이 있나."""
    return any(i.kind in ("unverified", "conflict") for i in items)


def _items_of_rejection(rej: Rejection, r_target: str) -> list[ReviewItem]:
    """거절이유 하나: 인용문헌에서 나온 줄이 있으면 거절이유 자신의 status 줄은 내지 않는다."""
    r_label = _text(rej.article)
    # 지원 안 하는 거절이유는 직접 검토 필요의 이유가 조문이다
    reason = (
        {Flag.NEEDS_HUMAN_REVIEW: f"지원 안 하는 거절이유 {r_label}"} if not rej.supported else {}
    )
    child: list[ReviewItem] = []
    for j, c in enumerate(rej.citations):
        c_target = f"{r_target}.citations[{j}]"
        c_label = _text(c.number)
        if c.country.status.value == StatusValue.UNVERIFIED:  # 나라를 못 정함
            child.append(
                ReviewItem(
                    kind="unverified",
                    target=c_target,
                    label=c_label,
                    reason=str(c.country.status.reason),
                )
            )
        if c.country.value is None:
            country_reason = f"나라를 못 정함 ({c.country.raw_text or '원문 글자 없음'})"
        else:
            country_reason = f"지원 안 하는 나라 {c.country.value}"
        child += _flag_items(c.flags, c_target, c_label, {Flag.NEEDS_HUMAN_REVIEW: country_reason})
    own = _items_of_result(rej, r_target, r_label, reason, skip_status=_status_lines(child))
    return own + child


def _items_of_oa_result(oa: OAResult, root: str) -> list[ReviewItem]:
    """OAResult 하나: 거절이유·인용문헌 안까지 내려가며 모은다. 원인은 가장 안쪽 한 곳에만."""
    rej_items: list[ReviewItem] = []
    counted = False  # OAResult status에 들어간(지원하는) 거절이유에서 status 줄이 나왔나
    for i, rej in enumerate(oa.rejections):
        got = _items_of_rejection(rej, f"{root}.rejections[{i}]")
        rej_items += got
        if rej.supported and _status_lines(got):
            counted = True
    return _items_of_result(oa, root, oa.oa_id, {}, skip_status=counted) + rej_items


def collect_review_items(results: list[ResultBase], materials: CaseMaterials) -> list[ReviewItem]:
    """결과들과 빠진 자료에서 검토할 사항을 모은다.

    OAResult는 거절이유·인용문헌 안까지 내려가 본다. 조회 범위 내 없음은 정상 답이라 넣지 않는다.
    """
    if not results:
        logger.warning("collect_review_items: 결과가 0개")
        return []

    items: list[ReviewItem] = []
    for i, r in enumerate(results):
        if isinstance(r, OAResult):
            root = "oa_result" if len(results) == 1 else f"oa_result[{i}]"
            items += _items_of_oa_result(r, root)
        else:
            items += _items_of_result(r, f"results[{i}]", type(r).__name__, {})
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
