"""누락 검사: 모든 거절이유 × 모든 대상 청구항이 판단 단위에 들어 있나 (순수 함수).

청구항 하나라도 대응이 빠지면 출원 전체가 거절되므로, 빠진 쌍을 찾아 사람에게 보인다.
(초안 검사 #40 때 core/verify/로 옮긴다.)
"""

import logging

from patent_ai.core.schemas.judgment_unit import JudgmentUnit
from patent_ai.core.schemas.oa_result import OAResult

logger = logging.getLogger(__name__)


def uncovered(oa: OAResult, units: list[JudgmentUnit]) -> list[tuple[int, int]]:
    """지원하는 거절이유의 대상 청구항 중 그 거절이유의 판단 단위에 없는 (거절이유, 청구항) 쌍.

    같은 청구항이 다른 거절이유의 묶음에 있어도 이 거절이유에서 빠졌으면 누락이다.
    지원 안 하는 거절이유는 판단 단위를 만들지 않으므로 여기서 세지 않는다 (따로 알린다).
    """
    missing: list[tuple[int, int]] = []
    for rej in oa.rejections:
        if not rej.supported:
            continue
        if rej.claims.value is None:
            continue  # 대상 청구항을 못 읽어 셀 수 없다. unchecked_rejections가 따로 알린다
        covered = {c for u in units if u.rejection == rej.no for c in u.claims}
        missing += [(rej.no, c) for c in sorted(set(rej.claims.value) - covered)]
    return missing


def unchecked_rejections(oa: OAResult) -> list[int]:
    """대상 청구항을 못 읽어 누락 검사를 하지 못한 (지원하는) 거절이유 번호.

    이 거절이유는 uncovered에 아무것도 안 나온다. "누락 없음"으로 읽히지 않게 따로 낸다.
    """
    unchecked = [r.no for r in oa.rejections if r.supported and r.claims.value is None]
    if unchecked:
        logger.warning("누락 검사: 거절이유 %s의 대상 청구항을 몰라 검사하지 못함", unchecked)
    return unchecked
