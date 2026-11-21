"""구성요소 나누기 (F3 ①): 청구항 하나의 원문 -> 구성요소 목록 + 인용 관계.

읽고 나누는 것은 모델이 한다. 코드는 확인만 한다:
- 구성요소 글자가 청구항 원문에 순서대로 그대로 있는지 (공백 줄이기만 허용)
- 인용구(depends_on_quote)가 원문에 있고, 인용 번호가 그 사건 청구항 번호이며 자기보다 작은지
코드는 "제N항"을 정규식으로 읽어 모델 답과 맞는지 확인만 한다 (나누기 자체는 모델).
확인에 떨어지면 검사 오류를 붙여 한 번 다시 부르고,
그래도 틀린 것은 버리지 않고 "확인되지 않음"으로 남긴다.
"""

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from patent_ai.core.f3_claim_compare.retry import call_checked, confirmed, unverified
from patent_ai.core.f3_claim_compare.textmatch import find_from, squeeze
from patent_ai.core.llm.limits import RunContext
from patent_ai.core.schemas.common import Status, StatusValue, UnverifiedReason, worst_status

logger = logging.getLogger(__name__)

STEP = "f3.split_elements"


# 인용구 안 "제N항" 또는 "제N항 내지/~ 제M항" (범위는 사이 번호까지 펼친다)
_CITE = re.compile(r"제\s*(\d+)\s*항(?:\s*(?:내지|~)\s*제?\s*(\d+)\s*항)?")
# 원문이 맨 앞에서 "제N항에 있어서/의/또는/내지 ..."처럼 앞 청구항을 인용하는 꼴 (넓히지 않는다)
_LEADING_CITE = re.compile(r"^\s*제\s*\d+\s*항(?=\s*(?:에|의|또는|내지|~|,))")


def cited_numbers(quote: str) -> set[int]:
    """인용구 글자에서 청구항 번호를 뽑는다 (확인용). 못 뽑으면 빈 집합."""
    numbers: set[int] = set()
    for m in _CITE.finditer(quote):
        first = int(m.group(1))
        last = int(m.group(2)) if m.group(2) else first
        numbers.update(range(first, max(first, last) + 1))
    return numbers


# ---- 모델이 돌려주는 출력 스키마 ----
class ElementText(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str  # 청구항 원문 그대로


class ClaimElements(BaseModel):
    """모델 답. 상태·위치는 없다: 원문 대조 결과라 코드가 정한다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: int
    depends_on: list[int] = []  # 인용하는 앞 청구항 번호 (독립항이면 빈 목록)
    depends_on_quote: str | None = None  # 인용하는 부분의 원문 글자
    elements: list[ElementText] = []


# ---- 결과 (F3 안쪽 모델. 결과 스키마 v0에는 오프셋·인용구 칸이 없다) ----
class ClaimElement(BaseModel):
    """구성요소 하나. 확인됨이면 text는 원문 글자 그대로이고 원문[start:end]와 같다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: int = Field(ge=1)
    no: int = Field(ge=1)  # 청구항 안 순번 (1부터)
    text: str  # 확인됨: 원문 글자 / 확인되지 않음: 모델이 준 글자
    element_location: str  # 사람이 읽는 위치 `청구항 1 [구성 1-2]`
    start: int | None = None  # 원문 글자 오프셋 (못 찾으면 None)
    end: int | None = None
    status: Status


class SplitClaim(BaseModel):
    """청구항 하나를 나눈 결과."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: int = Field(ge=1)
    elements: list[ClaimElement]
    depends_on: list[int] | None  # 확인된 인용 번호. 독립항이면 [], 확인 못 하면 None
    depends_on_quote: str | None  # 확인된 인용구 (원문 글자)
    depends_on_status: Status
    status: Status  # 구성요소·인용 관계 status 중 가장 나쁜 값


def element_location(claim: int, no: int) -> str:
    """사람이 읽는 구성요소 위치. 화면·대비표 줄이 같은 꼴을 쓴다."""
    return f"청구항 {claim} [구성 {claim}-{no}]"


@dataclass
class _Checked:
    """모델 답 하나를 원문과 대조한 결과. errors가 비면 모두 통과."""

    elements: list[ClaimElement]
    depends_on: list[int] | None
    depends_on_quote: str | None
    depends_on_status: Status
    errors: list[str] = field(default_factory=list)  # 다시 부를 때 모델에 보여 줄 검사 오류
    wrong_claim: bool = False  # 모델이 다른 청구항 번호로 답함


def _check(answer: ClaimElements, claim: int, claim_text: str, claim_numbers: set[int]) -> _Checked:
    squeezed, offsets = squeeze(claim_text)
    errors: list[str] = []
    wrong_claim = answer.claim != claim
    if wrong_claim:
        errors.append(f"claim은 {claim}이어야 함 (받은 값 {answer.claim})")

    # 1) 인용 관계: 인용구가 원문에 있는지, 번호가 이 사건의 앞 청구항인지만 본다
    depends_errors = _check_depends_on(answer, claim, claim_numbers, claim_text)
    quote = (answer.depends_on_quote or "").strip()
    quote_at = find_from(quote, squeezed, offsets, 0) if quote else None
    if quote and quote_at is None:
        depends_errors.append(f"depends_on_quote가 청구항 원문에 그대로 없음: {quote!r}")

    # 2) 구성요소: 앞 구성요소 끝 자리부터 차례로 찾는다 (순서가 바뀌거나 겹치면 못 찾음).
    #    종속항은 인용구가 끝난 자리부터 찾는다 (인용구 안의 같은 글자를 잡지 않게)
    cursor = quote_at[2] if quote_at else 0
    spots: list[tuple[int, int, int, int] | None] = []  # (원문 start, end, 줄인 글 start, end)
    for item in answer.elements:
        found = find_from(item.text, squeezed, offsets, cursor)
        if found is None:
            spots.append(None)
            continue
        start, end, cursor = found
        spots.append((start, end, cursor - len(" ".join(item.text.split())), cursor))

    elements: list[ClaimElement] = []
    for i, (item, spot) in enumerate(zip(answer.elements, spots, strict=True)):
        no = i + 1
        status = confirmed("구성요소 글자가 청구항 원문에 순서대로 그대로 있음")
        if spot is None:
            errors.append(
                f"elements[{i}].text가 청구항 원문에 그대로 없거나 앞 구성요소보다 앞에 있음: "
                f"{item.text!r}"
            )
            status = unverified(UnverifiedReason.NOT_EXTRACTED)
        else:
            # 같은 글자가 다음 구성요소 자리 앞에 또 있으면 어느 것인지 원문만으로 못 가린다
            later = [s for s in spots[i + 1 :] if s is not None]
            bound = later[0][2] if later else len(squeezed)
            wanted = squeezed[spot[2] : spot[3]]
            if squeezed.find(wanted, spot[2] + 1, bound) >= 0:
                errors.append(
                    f"elements[{i}].text와 같은 글자가 원문에 여러 번 있어 위치를 못 정함 "
                    f"(앞뒤 글자를 더 넣어 하나로 정해지게): {item.text!r}"
                )
                status = unverified(UnverifiedReason.AMBIGUOUS)
        located = spot is not None and status.value == StatusValue.CONFIRMED
        # 버리지 않는다. 위치를 못 정한 것은 모델이 준 글자 그대로 "확인되지 않음"으로 남긴다
        elements.append(
            ClaimElement(
                claim=claim,
                no=no,
                text=claim_text[spot[0] : spot[1]] if located else item.text,
                element_location=element_location(claim, no),
                start=spot[0] if located else None,
                end=spot[1] if located else None,
                status=status,
            )
        )
    if not answer.elements:
        errors.append("elements가 비어 있음 (구성요소가 0개)")

    if depends_errors:
        errors += depends_errors
        bad = unverified(UnverifiedReason.NOT_EXTRACTED)
        return _Checked(elements, None, None, bad, errors, wrong_claim)
    if not answer.depends_on:
        # 독립항 여부는 모델이 읽은 그대로다. 인용구가 없어 코드가 원문과 대조할 것이 없다
        # (값은 confirmed로 두되 무엇을 확인했는지에 "대조 없음"을 분명히 적는다. 사람 판단 대기)
        status = confirmed("독립항 여부는 모델 판단 (인용구 없음, 원문 대조 없음)")
        return _Checked(elements, [], None, status, errors, wrong_claim)
    status = confirmed("인용구가 청구항 원문에 있고 인용 번호가 이 사건의 앞 청구항임")
    quote_text = claim_text[quote_at[0] : quote_at[1]]
    depends_on = sorted(set(answer.depends_on))
    return _Checked(elements, depends_on, quote_text, status, errors, wrong_claim)


def _check_depends_on(
    answer: ClaimElements, claim: int, claim_numbers: set[int], claim_text: str
) -> list[str]:
    """인용 번호와 인용구가 서로 맞는지. 틀린 점을 글로 돌려준다 (없으면 빈 목록).

    오류는 다시 부를 때 모델에 보여 주고, 두 번째 답도 틀리면 인용 관계는 확인되지 않음이 된다.
    """
    errors: list[str] = []
    has_quote = bool((answer.depends_on_quote or "").strip())
    if answer.depends_on and not has_quote:
        errors.append("depends_on이 있는데 depends_on_quote(인용하는 원문 글자)가 없음")
    if has_quote and not answer.depends_on:
        errors.append("depends_on_quote가 있는데 depends_on(인용 번호)이 비어 있음")
    for n in answer.depends_on:
        if n not in claim_numbers:
            errors.append(f"depends_on의 {n}은 이 사건의 청구항 번호가 아님")
        elif n >= claim:
            errors.append(f"depends_on의 {n}은 청구항 {claim}보다 앞 번호가 아님")
    # 인용구 글자 속 번호와 모델이 준 depends_on이 같은지 (인용구가 있을 때)
    if has_quote and answer.depends_on:
        in_quote = cited_numbers(answer.depends_on_quote or "")
        if in_quote and in_quote != set(answer.depends_on):
            errors.append(
                f"depends_on {sorted(set(answer.depends_on))}이 인용구 속 청구항 번호 "
                f"{sorted(in_quote)}와 다름"
            )
    # 인용구 없이 독립항으로 답했는데 원문이 "제N항에 있어서"처럼 시작하면 놓친 것이다
    if not has_quote and not answer.depends_on and _LEADING_CITE.match(claim_text):
        errors.append("청구항 원문이 앞 청구항을 인용하며 시작하는데 depends_on이 비어 있음")
    return errors


# ---- 모델 호출 (검사 실패면 검사 오류를 붙여 한 번 더: retry.call_checked) ----
def _ask(claim: int, claim_text: str, claim_numbers: set[int], ctx: RunContext) -> _Checked:
    """모델을 부르고 원문과 대조한다. 대조에 떨어지면 검사 오류를 붙여 한 번만 더 부른다."""
    variables = {
        "claim": str(claim),
        "claim_text": claim_text,
        "claim_numbers": ", ".join(str(n) for n in sorted(claim_numbers)),
        "retry_note": "",
    }

    def check(answer: ClaimElements) -> tuple[_Checked, list[str]]:
        checked = _check(answer, claim, claim_text, claim_numbers)
        return checked, checked.errors

    who = f"split_elements 청구항 {claim}"
    return call_checked(STEP, variables, ClaimElements, check, ctx=ctx, who=who)


def split_elements(
    claim: int, claim_text: str, claim_numbers: Iterable[int], *, ctx: RunContext
) -> SplitClaim:
    """청구항 하나를 구성요소로 나눈다.

    claim_numbers: 그 사건의 OA 당시 청구항 번호 전부 (인용 번호 확인에 쓴다).
    같은 입력과 같은 모델 답이면 결과가 같다 (코드 쪽은 정해진 대조만 한다).
    """
    # 청구항 글자가 없으면 모델을 부르지 않는다
    if not claim_text.strip():
        logger.warning("split_elements 청구항 %d: 청구항 글자가 비어 모델을 부르지 않음", claim)
        bad = unverified(UnverifiedReason.INPUT_UNVERIFIED)
        return SplitClaim(
            claim=claim,
            elements=[],
            depends_on=None,
            depends_on_quote=None,
            depends_on_status=bad,
            status=bad,
        )

    checked = _ask(claim, claim_text, set(claim_numbers), ctx)

    # 다시 불러도 남은 문제는 경고로 남긴다 (원문 글자는 로그에 쓰지 않는다)
    statuses = [e.status for e in checked.elements] + [checked.depends_on_status]
    if not checked.elements:
        logger.warning("split_elements 청구항 %d: 구성요소가 0개 (확인되지 않음으로 남김)", claim)
        statuses.insert(0, unverified(UnverifiedReason.NOT_EXTRACTED))
    lost = [e.no for e in checked.elements if e.status.value != StatusValue.CONFIRMED]
    if lost:
        logger.warning(
            "split_elements 청구항 %d: 구성요소 %s를 원문에서 못 찾음 (확인되지 않음으로 남김)",
            claim,
            lost,
        )
    if checked.depends_on_status.value != StatusValue.CONFIRMED:
        logger.warning("split_elements 청구항 %d: 인용 관계를 확인하지 못함", claim)
    if checked.wrong_claim:
        # 다시 불러도 다른 청구항 번호로 답했다: 다른 청구항을 나눈 답일 수 있어 애매로 낮춘다
        # (결과의 번호는 입력으로 아는 값을 쓴다)
        logger.warning("split_elements 청구항 %d: 모델이 다른 청구항 번호로 답함", claim)
        statuses.insert(0, unverified(UnverifiedReason.AMBIGUOUS))
    return SplitClaim(
        claim=claim,
        elements=checked.elements,
        depends_on=checked.depends_on,
        depends_on_quote=checked.depends_on_quote,
        depends_on_status=checked.depends_on_status,
        status=worst_status(statuses, "구성요소 글자와 인용구를 청구항 원문과 대조함"),
    )
