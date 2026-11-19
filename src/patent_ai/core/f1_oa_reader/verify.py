"""원문 대조·합치기 (design.md 2절 ⑤). 규칙 값과 모델 값을 원문 쪽 글자와 맞춰 합친다."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from patent_ai.core.f1_oa_reader.tables import cells_from_page
from patent_ai.core.schemas.common import (
    Candidate,
    ExtractedValue,
    Status,
    StatusValue,
    UnverifiedReason,
)
from patent_ai.core.schemas.document import PageText

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Found:
    """뽑은 값 하나 (규칙이든 모델이든). 두 쪽 값을 이 모양으로 맞춰 merge에 넘긴다."""

    value: Any | None
    raw_text: str | None
    page: int | None
    ambiguous: bool = False


def _squash(text: str) -> str:
    """공백·줄바꿈을 모두 없앤다 (대조에서 무시할 것은 이것뿐)."""
    return "".join(text.split())


def raw_text_on_page(pages: PageText, page: int, raw_text: str) -> bool:
    """raw_text가 그 쪽 글자에 실제로 있나. 없는 쪽 번호면 False.

    쪽 글자에 없으면 그 쪽에서 시작하는 표 칸(다음 쪽으로 넘어간 칸은 이어 붙인 것)에서도 찾는다.
    칸 글자도 PDF에서 뽑은 원문이라 지어낸 값은 여기서도 통과하지 못한다.
    """

    needle = _squash(raw_text)
    if not needle:
        return False
    for p in pages.pages:
        if p.page == page:
            if needle in _squash(p.text):
                return True
            return any(needle in _squash(cell) for cell in cells_from_page(pages, page))
    return False


def _passes(found: Found, pages: PageText) -> bool:
    """글자와 쪽이 다 있고, 그 쪽에 글자가 실제로 있나."""
    if found.raw_text is None or found.page is None:
        return False
    return raw_text_on_page(pages, found.page, found.raw_text)


def unverified(
    reason: UnverifiedReason, found: Found | None = None, *, keep_location: bool = False
) -> ExtractedValue:
    """값 없는 확인되지 않음. 대조를 통과한 자리만 남긴다."""
    status = Status(value=StatusValue.UNVERIFIED, reason=reason)
    if found is not None and keep_location:
        return ExtractedValue(value=None, raw_text=found.raw_text, page=found.page, status=status)
    return ExtractedValue(value=None, status=status)


def merge(
    rule: Found | None,
    model: Found | None,
    pages: PageText,
    *,
    compare_by: Literal["value", "raw_text"] = "value",
    derive: Callable[[str], Any] | None = None,
    field: str = "",
) -> ExtractedValue:
    """규칙 값과 모델 값을 원문 대조 뒤 합친다 (design.md 필드 출처 표).

    compare_by="raw_text": 날짜처럼 value 없이 글자만 비교하는 필드.
    derive: 있으면 쓸 값은 원문 글자에서 다시 뽑는다 (넘어온 value는 무시, None이면 그쪽은 못 씀).
    field: 로그에 찍을 필드 이름 (값 글자는 찍지 않는다).
    """
    given = [("rule", rule), ("model", model)]
    given = [(s, f) for s, f in given if f is not None]
    # 1) 둘 다 안 뽑았다
    if not given:
        return unverified(UnverifiedReason.NOT_EXTRACTED)

    # 2) 한쪽이라도 애매 표시면 다른 쪽이 통과해도 확인되지 않음.
    #    글자·쪽은 대조에 통과한 쪽 것 (애매 쪽 먼저)
    ambiguous = [f for _, f in given if f.ambiguous]
    if ambiguous:
        others = [f for _, f in given if not f.ambiguous]
        for f in ambiguous + others:
            if _passes(f, pages):
                return unverified(UnverifiedReason.AMBIGUOUS, f, keep_location=True)
        return unverified(UnverifiedReason.AMBIGUOUS)

    # 3) 쓸 값: 원문 대조 통과 + (값은 원문 글자에서 나온 것이어야 함)
    usable: list[tuple[Literal["rule", "model"], Found, Any]] = []
    for source, f in given:
        if not _passes(f, pages):
            logger.info("원문 대조 실패로 버림: field=%s source=%s page=%s", field, source, f.page)
            continue
        if compare_by == "raw_text":
            value = None
        elif derive is not None:
            value = derive(f.raw_text or "")  # 글자에서 다시 뽑는다
        elif f.value is not None and _squash(str(f.value)) in _squash(f.raw_text or ""):
            value = f.value
        else:
            value = None
        if compare_by == "value" and value is None:
            logger.info(
                "값이 원문 글자와 안 맞아 버림: field=%s source=%s page=%s", field, source, f.page
            )
            continue
        usable.append((source, f, value))

    if not usable:
        return unverified(UnverifiedReason.NOT_EXTRACTED)

    def key(item: tuple[str, Found, Any]) -> Any:
        return _squash(item[1].raw_text or "") if compare_by == "raw_text" else item[2]

    _, first, first_value = usable[0]
    if len(usable) == 2 and key(usable[0]) != key(usable[1]):
        # 4) 둘 다 통과했는데 다르면 충돌: 값은 비우고 둘 다 남긴다
        return ExtractedValue(
            status=Status(value=StatusValue.CONFLICT),
            candidates=[
                Candidate(value=v, raw_text=f.raw_text, page=f.page, source=s) for s, f, v in usable
            ],
        )
    # 5) 같거나 하나만 통과: 그 값 (둘이면 규칙 쪽 글자·쪽)
    return ExtractedValue(
        value=first_value,
        raw_text=first.raw_text,
        page=first.page,
        status=Status(value=StatusValue.CONFIRMED, checked=f"{first.page}쪽 원문 대조"),
    )
