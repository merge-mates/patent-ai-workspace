"""OA 당시 청구항 전체의 인용 관계표 (ADR 0005 결정 1). 코드 도구, 모델 호출 없음.

청구항 앞머리("…에 있어서", "…에 따른" 앞)의 인용 표시만 읽는다:
"제N항", "제 N 항", "청구항 N", "제N항 또는 제M항", "제N항 내지 제M항"(범위는 펼친다).
- 인용이 없으면 독립항 → `depends_on = []`. 번호 없는 전제부("…방법에 있어서")도 독립항이다.
- 앞머리에 항을 가리키는 말이 있는데 번호를 못 읽으면 `depends_on = None` (확인되지 않음) + 경고.
  못 찾음을 "독립항"으로 쓰지 않는다 (못 찾음 ≠ 없음).

F3 청구항 나누기(`SplitClaim.depends_on`)는 거절 대상 항과 그 앞 항만 나누고 결과에 싣지 않아,
F4가 보정 범위를 정하려고 청구항 전체의 표를 따로 만든다 (ADR 0005 결정 1).
규칙은 실험 `m3-i2-f4-amendment-scope` 사전 점검에서 쓴 것과 같다
(tune 105항·294항에서 못 읽음 0·1항).
"""

import logging
import re

from pydantic import BaseModel, ConfigDict

from patent_ai.core.f4_response_draft.inputs import ClaimText

logger = logging.getLogger(__name__)

# 인용 표시는 청구항 앞머리에만 있다: "…에 있어서" / "…에 따른" 등의 앞까지만 본다
_HEAD_END = re.compile(r"(있어서|에\s*따른|에\s*기재된|에\s*의한)")
_HEAD_SCAN = 300  # 앞머리 끝말을 찾는 범위 (글자)
_HEAD_FALLBACK = 120  # 끝말이 없을 때 앞머리로 볼 길이 (글자)
# "제 1 항", "제1항", "청구항 1" 모두 받는다
_NUM = r"(?:제\s*(\d+)\s*항|청구항\s*(\d+))"
_RANGE = re.compile(_NUM + r"\s*(?:내지|~|-|부터)\s*" + _NUM)
_SINGLE = re.compile(_NUM)
# 항을 가리키는 말: 이것이 있는데 번호를 못 읽으면 확인되지 않음
_POINTS_TO_CLAIM = re.compile(r"(청구항|\d+\s*항|항\s*중|어느\s*한\s*항)")


class ClaimRef(BaseModel):
    """청구항 하나의 인용 관계."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: int
    depends_on: list[int] | None  # []: 독립항, None: 인용을 읽지 못함 (확인되지 않음)
    head: str  # 읽은 앞머리 글자 (사람이 대조할 때 본다)


def _num(m: re.Match, i: int) -> int:
    # _NUM 묶음은 (제N항, 청구항N) 둘 중 하나만 채워진다
    return int(m.group(i) or m.group(i + 1))


def _parse(claim: int, text: str) -> ClaimRef:
    end = _HEAD_END.search(text[:_HEAD_SCAN])
    head = text[: end.start()] if end else text[:_HEAD_FALLBACK]
    refs: set[int] = set()
    # 범위("제1항 내지 제12항")를 먼저 펼치고, 그 글자는 지워 낱개 읽기에 다시 걸리지 않게 한다
    for r in _RANGE.finditer(head):
        a, b = _num(r, 1), _num(r, 3)
        refs |= set(range(min(a, b), max(a, b) + 1))
    refs |= {_num(s, 1) for s in _SINGLE.finditer(_RANGE.sub(" ", head))}
    refs = {r for r in refs if r < claim}  # 종속항은 앞 청구항만 인용한다
    if not refs and _POINTS_TO_CLAIM.search(head):
        logger.warning(
            "claim_refs: 청구항 %d이 항을 가리키는데 번호를 못 읽음 (확인되지 않음)",
            claim,
        )
        return ClaimRef(claim=claim, depends_on=None, head=head.strip())
    return ClaimRef(claim=claim, depends_on=sorted(refs), head=head.strip())


def claim_refs(claims_text: list[ClaimText]) -> dict[int, ClaimRef]:
    """청구항 번호 -> 인용 관계. 같은 입력 -> 같은 결과."""
    if not claims_text:
        logger.warning("claim_refs: 청구항 글자가 0개라 인용 관계표가 비었음")
        return {}
    return {c.claim: _parse(c.claim, c.text) for c in sorted(claims_text, key=lambda c: c.claim)}
