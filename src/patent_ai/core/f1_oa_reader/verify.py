"""원문 대조·합치기 (design.md 2절 ⑤). 규칙 값과 모델 값을 원문 쪽 글자와 맞춰 합친다."""

import logging
from dataclasses import dataclass
from typing import Any, Literal

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
    """뽑은 값 하나 (규칙이든 모델이든). 나중에 rules.Candidate와 맞춘다."""

    value: Any | None
    raw_text: str | None
    page: int | None
    ambiguous: bool = False


def _squash(text: str) -> str:
    """공백·줄바꿈을 모두 없앤다 (대조에서 무시할 것은 이것뿐)."""
    return "".join(text.split())


def raw_text_on_page(pages: PageText, page: int, raw_text: str) -> bool:
    """raw_text가 그 쪽 글자에 실제로 있나. 없는 쪽 번호면 False."""
    needle = _squash(raw_text)
    if not needle:
        return False
    for p in pages.pages:
        if p.page == page:
            return needle in _squash(p.text)
    return False


def _passes(found: Found, pages: PageText) -> bool:
    """글자와 쪽이 다 있고, 그 쪽에 글자가 실제로 있나."""
    if found.raw_text is None or found.page is None:
        return False
    return raw_text_on_page(pages, found.page, found.raw_text)


def _unverified(
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
) -> ExtractedValue:
    """규칙 값과 모델 값을 원문 대조 뒤 합친다 (design.md 필드 출처 표).

    compare_by="raw_text": 날짜처럼 value 없이 글자만 비교하는 필드.
    """
    # 1) 안 뽑은 것(None)은 뺀다
    given = [("rule", f) for f in (rule,) if f] + [("model", f) for f in (model,) if f]
    if not given:
        return _unverified(UnverifiedReason.NOT_EXTRACTED)

    # 2) 애매 표시가 아니고, value 비교면 value도 있으며, 원문 대조를 통과한 것만 "쓸 수 있는 값"
    usable = []
    for source, f in ((("rule", rule)), ("model", model)):
        if f is None or f.ambiguous or not _passes(f, pages):
            continue
        if compare_by == "value" and f.value is None:
            continue
        usable.append((source, f))

    if not usable:
        # 3) 쓸 수 있는 값이 없다: 애매 표시가 있으면 ambiguous, 아니면 못 뽑음
        for _, f in given:
            if f.ambiguous:
                return _unverified(UnverifiedReason.AMBIGUOUS, f, keep_location=_passes(f, pages))
        return _unverified(UnverifiedReason.NOT_EXTRACTED)

    def key(f: Found) -> Any:
        return _squash(f.raw_text or "") if compare_by == "raw_text" else f.value

    first = usable[0][1]
    if len(usable) == 2 and key(usable[0][1]) != key(usable[1][1]):
        # 4) 둘 다 통과했는데 다르면 충돌: 값은 비우고 둘 다 남긴다
        return ExtractedValue(
            status=Status(value=StatusValue.CONFLICT),
            candidates=[
                Candidate(value=f.value, raw_text=f.raw_text, page=f.page, source=s)  # type: ignore[arg-type]
                for s, f in usable
            ],
        )
    # 5) 같거나 하나만 통과: 그 값 (둘이면 규칙 쪽 글자·쪽)
    return ExtractedValue(
        value=None if compare_by == "raw_text" else first.value,
        raw_text=first.raw_text,
        page=first.page,
        status=Status(value=StatusValue.CONFIRMED, checked=f"{first.page}쪽 원문 대조"),
    )
