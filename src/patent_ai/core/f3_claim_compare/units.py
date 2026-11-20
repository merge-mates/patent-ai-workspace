"""판단 단위(②) 만들기: 거절이유의 대상 청구항 + 확인된 인용 관계 -> JudgmentUnit 목록.

답이 정해진 코드 도구다 (같은 입력 -> 같은 결과). 청구항을 읽는 일(누가 누구를 인용하나)은
구성요소 나누기 단계의 모델이 했고, 여기서는 그 결과(SplitClaim.depends_on)를 규칙대로 묶기만 한다.
- 진보성·신규성: 독립항 묶음. 여러 항을 인용하는 종속항은 그 독립항 묶음마다 들어간다.
- 명확성: 청구항 하나. 함께 읽을 청구항(read_with)은 인용을 거슬러 올라간 앞 청구항 전부.
"""

import logging
from collections.abc import Mapping

from patent_ai.core.f3_claim_compare.elements import SplitClaim
from patent_ai.core.schemas.case_materials import HeldTask
from patent_ai.core.schemas.common import Flag, Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.judgment_unit import JudgmentUnit, UnitKind
from patent_ai.core.schemas.oa_result import OAResult, Rejection, RejectionKind

logger = logging.getLogger(__name__)

_CHECKED = "거절이유 대상 청구항과 확인된 인용 관계로 묶음"


def _ancestors(claim: int, splits: Mapping[int, SplitClaim]) -> set[int] | None:
    """인용을 거슬러 올라간 앞 청구항 전부. 중간에 인용 관계를 모르는 청구항이 있으면 None."""
    seen: set[int] = set()
    todo = [claim]
    while todo:
        split = splits.get(todo.pop())
        if split is None or split.depends_on is None:
            return None  # 나눈 결과가 없거나 인용 관계를 확인하지 못함
        for parent in split.depends_on:
            if parent not in seen:
                seen.add(parent)
                todo.append(parent)
    return seen


def _roots(claim: int, ancestors: set[int], splits: Mapping[int, SplitClaim]) -> list[int]:
    """그 청구항이 속한 묶음의 독립항들 (자기가 독립항이면 자기)."""
    if not ancestors:
        return [claim]
    return sorted(a for a in ancestors if splits[a].depends_on == [])


def _unit(rej: Rejection, oa_id: str, kind: UnitKind, rep: int, claims: list[int], **more):
    # 대상 청구항 값이 원문 대조를 통과했고 인용 관계를 다 확인했을 때만 확인됨
    known = more.pop("known")
    ok = known and rej.claims.status.value == StatusValue.CONFIRMED
    return JudgmentUnit(
        unit_id=f"{oa_id}:{rej.article.value}:c{rep}",
        rejection=rej.no,
        rejection_kind=rej.kind,
        unit_kind=kind,
        representative_claim=rep,
        claims=claims,
        order=1,  # 아래에서 다시 매긴다
        status=Status(value=StatusValue.CONFIRMED, checked=_CHECKED)
        if ok
        else Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.INPUT_UNVERIFIED),
        flags=[] if ok else [Flag.NEEDS_HUMAN_REVIEW],
        **more,
    )


def _units_of(rej: Rejection, oa_id: str, splits: Mapping[int, SplitClaim]) -> list[JudgmentUnit]:
    targets = sorted(set(rej.claims.value or []))
    family = {c: _ancestors(c, splits) for c in targets}
    unknown = [c for c in targets if family[c] is None]
    if unknown:
        logger.warning(
            "build_units 거절이유 %d: 청구항 %s의 인용 관계를 몰라 혼자 단위로 둠", rej.no, unknown
        )

    if rej.kind == RejectionKind.CLARITY:
        # 명확성: 청구항 하나가 단위. 독립항 먼저
        ordered = sorted(targets, key=lambda c: (bool(family[c]) or family[c] is None, c))
        return [
            _unit(
                rej,
                oa_id,
                UnitKind.SINGLE_CLAIM,
                c,
                [c],
                read_with=sorted(family[c] or []),
                known=family[c] is not None,
            )
            for c in ordered
        ]

    # 진보성·신규성: 독립항마다 묶는다. 묶음 열쇠 = 독립항 번호
    groups: dict[int, list[int]] = {}
    for c in targets:
        if family[c] is None:
            continue
        for root in _roots(c, family[c], splits):
            groups.setdefault(root, []).append(c)
    units = []
    for root in sorted(groups):
        members = groups[root]
        # 독립항이 이 거절이유의 대상이 아니면 대상 중 가장 앞 청구항이 대표
        rep = root if root in members else members[0]
        units.append(_unit(rej, oa_id, UnitKind.INDEPENDENT_GROUP, rep, members, known=True))
    units += [_unit(rej, oa_id, UnitKind.INDEPENDENT_GROUP, c, [c], known=False) for c in unknown]
    return units


def build_units(
    oa: OAResult, splits: Mapping[int, SplitClaim]
) -> tuple[list[JudgmentUnit], list[HeldTask]]:
    """OA 정리 결과의 거절이유마다 판단 단위를 만든다.

    splits: 청구항 번호 -> 나눈 결과 (인용 관계를 여기서 읽는다).
    돌려주는 값: (단위 목록, 단위를 못 만들어 보류한 작업).
    """
    units: list[JudgmentUnit] = []
    held: list[HeldTask] = []
    seen: set[str] = set()
    for rej in sorted(oa.rejections, key=lambda r: r.no):
        if not rej.supported or rej.kind == RejectionKind.OTHER:
            continue  # 지원 안 하는 거절이유는 단위를 만들지 않는다 (OA 결과의 flags로만 남음)
        if not rej.claims.value:
            logger.warning("build_units 거절이유 %d: 대상 청구항을 몰라 단위를 못 만듦", rej.no)
            held.append(
                HeldTask(
                    task=f"f3_units:{oa.oa_id}:r{rej.no}",
                    waiting_for="거절이유의 대상 청구항 확인 (직접 확인)",
                )
            )
            continue
        for unit in _units_of(rej, oa.oa_id, splits):
            if unit.unit_id in seen:
                # unit_id 꼴(OA:조문:c대표)로는 같은 조문·같은 대표 청구항 둘을 나눌 수 없다
                logger.warning("build_units: 같은 unit_id %s가 또 나와 보류함", unit.unit_id)
                held.append(
                    HeldTask(
                        task=f"f3_units:{oa.oa_id}:r{rej.no}:c{unit.representative_claim}",
                        waiting_for=f"같은 단위 {unit.unit_id}가 이미 있음 (직접 확인)",
                    )
                )
                continue
            seen.add(unit.unit_id)
            units.append(unit)
    if not units:
        logger.warning("build_units %s: 판단 단위가 0개", oa.oa_id)
    return [u.model_copy(update={"order": i}) for i, u in enumerate(units, start=1)], held
