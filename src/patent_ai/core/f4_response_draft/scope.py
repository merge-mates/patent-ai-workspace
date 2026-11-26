"""F4 보정 범위 (ADR 0005 결정 2·6). 코드 도구, 같은 입력 -> 같은 결과.

판단 단위(`JudgmentUnit`)는 F3 대비 단위로 그대로 두고,
F4가 묶음마다 "보정에 쓸 수 있는 항"을 따로 정한다.
- 진보성·신규성 묶음: 같은 거절이유의 진보성·신규성 묶음 전부의 청구항이 거슬러 닿는 독립항들
  + 그 독립항을 거슬러 인용하는 모든 항. 병렬 독립항(장치·방법·매체)의 가족도 함께 들어간다
  (실험 m3-i2-f4-amendment-scope 사전 점검: 묶음 독립항만 보면 정답 출처 23쌍 중 13쌍만 덮음).
- 여러 항을 인용하는 항은 닿는 독립항마다 들어간다.
- 명확성 묶음: 넓히지 않는다 (`claims + read_with`).
- 인용을 모르는 항(`depends_on = None`)은 넓힌 범위에 넣지 않고 `unknown_refs`에 남긴다 (경고).
  묶음 청구항은 인용을 몰라도 늘 범위에 든다 (지금보다 좁아지지 않게).
"""

import logging

from pydantic import BaseModel, ConfigDict

from patent_ai.core.f4_response_draft.claim_refs import ClaimRef
from patent_ai.core.schemas.judgment_unit import JudgmentUnit
from patent_ai.core.schemas.oa_result import RejectionKind

logger = logging.getLogger(__name__)


class AmendmentScope(BaseModel):
    """묶음 하나의 보정 범위. 모두 오름차순 청구항 번호."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_id: str
    claims: list[int]  # 보정 후보에 쓸 수 있는 항 전부
    targets: list[int]  # 이 묶음의 거절 대상 항 (unit.claims)
    same_rejection_targets: list[int]  # 같은 거절이유의 다른 묶음 대상 항 (범위 안)
    widened: list[int]  # 범위만 넓힌 항 (거절 대상 아님 → F3 대비 없음)
    unknown_refs: list[int]  # 인용을 몰라 넓힌 범위에서 뺀 항


def _roots(n: int, refs: dict[int, ClaimRef]) -> set[int] | None:
    """n이 거슬러 닿는 독립항들. 가는 길에 인용을 모르는 항이 있으면 None."""
    ref = refs.get(n)
    if ref is None or ref.depends_on is None:
        return None
    if not ref.depends_on:
        return {n}
    out: set[int] = set()
    for parent in ref.depends_on:  # 인용은 늘 앞 번호라 돌아오는 길이 없다
        up = _roots(parent, refs)
        if up is None:
            return None
        out |= up
    return out


def amendment_scope(
    unit: JudgmentUnit, units: list[JudgmentUnit], refs: dict[int, ClaimRef]
) -> AmendmentScope:
    """이 묶음(unit)의 보정 범위. units는 같은 OA의 판단 단위 전부 (같은 거절이유 묶음을 찾는다)."""
    own = sorted({*unit.claims, *unit.read_with})
    if unit.rejection_kind == RejectionKind.CLARITY:
        # 명확성 보정은 그 항 안에서 끝나는 경우가 대부분이라 넓히지 않는다 (ADR 0005 결정 2)
        return AmendmentScope(
            unit_id=unit.unit_id,
            claims=own,
            targets=sorted(unit.claims),
            same_rejection_targets=[],
            widened=[],
            unknown_refs=[],
        )
    if not refs:
        logger.warning("amendment_scope %s: 인용 관계표가 비어 묶음 청구항만 씀", unit.unit_id)

    same = [
        u
        for u in units
        if u.rejection == unit.rejection and u.rejection_kind != RejectionKind.CLARITY
    ]
    all_targets = {c for u in same for c in u.claims}
    # 같은 거절이유 대상 항이 닿는 독립항들
    roots: set[int] = set()
    for c in all_targets:
        roots |= _roots(c, refs) or set()
    unknown = sorted(n for n, r in refs.items() if r.depends_on is None)
    family = {n for n in refs if (r := _roots(n, refs)) is not None and r & roots}
    if unknown:
        logger.warning(
            "amendment_scope %s: 인용을 모르는 청구항 %s는 넓힌 범위에서 뺌", unit.unit_id, unknown
        )
    claims = sorted(family | set(own))
    others = sorted(c for c in all_targets - set(unit.claims) if c in claims)
    widened = sorted(set(claims) - all_targets - set(unit.read_with))
    return AmendmentScope(
        unit_id=unit.unit_id,
        claims=claims,
        targets=sorted(unit.claims),
        same_rejection_targets=others,
        widened=widened,
        unknown_refs=unknown,
    )
