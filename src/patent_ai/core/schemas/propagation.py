"""상태 전파와 검토할 사항 모으기. 규칙은 docs/data-model.md 3절 규칙 1·2."""

import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict

from patent_ai.core.schemas.case_materials import CaseMaterials
from patent_ai.core.schemas.common import (
    ResultBase,
    Status,
    StatusValue,
    UnverifiedReason,
)

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
    target: str  # 어느 결과(또는 자료)인가
    reason: str


def collect_review_items(results: list[ResultBase], materials: CaseMaterials) -> list[ReviewItem]:
    """결과들과 빠진 자료에서 검토할 사항을 모은다.

    조회 범위 내 없음은 정상 답이라 넣지 않는다.
    """
    if not results:
        logger.warning("collect_review_items: 결과가 0개")
        return []

    items: list[ReviewItem] = []
    for i, r in enumerate(results):
        target = f"{type(r).__name__}[{i}]"
        if r.status.value == StatusValue.UNVERIFIED:
            items.append(ReviewItem(kind="unverified", target=target, reason=str(r.status.reason)))
        elif r.status.value == StatusValue.CONFLICT:
            items.append(ReviewItem(kind="conflict", target=target, reason="값이 서로 충돌"))
        if r.needs_recheck:
            items.append(
                ReviewItem(kind="needs_recheck", target=target, reason=r.recheck_reason or "")
            )
        for flag in r.flags:  # 직접 판단/검토 필요 표시는 값 그대로 kind가 된다
            items.append(ReviewItem(kind=flag.value, target=target, reason=flag.value))
    for m in materials.missing:
        items.append(
            ReviewItem(kind="missing_material", target=m.what, reason=str(m.lookup_result))
        )
    return items
