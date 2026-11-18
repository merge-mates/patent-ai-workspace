"""청구항 줄(claim_rows) 만들기: 모델이 준 원문 글자를 코드가 대조하고 해석한다.

정답 형식은 docs/evaluation/f1-oa-gold.md 2.4·3절.
모델 값(value)은 쓰지 않고 원문 글자에서 다시 뽑는다.
대조에 떨어지면 그 줄만 확인되지 않음(값 버림)이고, 지원 안 하는 거절이유의 줄은 만들지 않는다.
"""

import logging
import re
from collections.abc import Callable

from patent_ai.core.f1_oa_reader.extraction import (
    ClaimRowExtraction,
    Item,
    RowCitationExtraction,
)
from patent_ai.core.f1_oa_reader.rules import parse_cited_locations, parse_same_as, quoted_segments
from patent_ai.core.f1_oa_reader.verify import raw_text_on_page
from patent_ai.core.schemas.common import Origin, Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.document import PageText
from patent_ai.core.schemas.oa_result import ClaimRow, RejectionKind, kind_of_article

logger = logging.getLogger(__name__)

_QUOTE_CHARS = " '\"‘’“”「」『』"
_NO_LOCATION = "위치 없음"


class _Fail(Exception):
    """줄의 값을 원문과 못 맞췄다. 이유는 status.reason이 된다."""

    def __init__(self, reason: UnverifiedReason = UnverifiedReason.NOT_EXTRACTED):
        self.reason = reason


def _squash(text: str) -> str:
    return "".join(text.split())


def _on_page(item: Item | None, pages: PageText) -> bool:
    """글자와 쪽이 다 있고 그 쪽에 글자가 실제로 있나."""
    return (
        item is not None
        and item.raw_text is not None
        and item.page is not None
        and raw_text_on_page(pages, item.page, item.raw_text)
    )


def _need(item: Item | None, pages: PageText) -> str:
    """대조를 통과한 원문 글자. 못 맞추면 _Fail."""
    if item is None or not _on_page(item, pages):
        raise _Fail()
    return item.raw_text or ""


def _all_items(r: ClaimRowExtraction) -> list[Item | None]:
    items: list[Item | None] = [r.claims, r.judgment, *r.same_as, *r.clarity_terms]
    for c in r.citations:
        items += [c.number, c.location, c.no_location]
    return items


def _labels_of(rejections: list[dict]) -> dict[str, str]:
    """거절이유 표의 인용문헌: 번호 글자(공백 없앰)·키 -> 라벨. 라벨 자체도 키로 둔다."""
    known: dict[str, str] = {}
    for rej in rejections:
        for c in rej["citations"]:
            known[c.label] = c.label
            if c.number.raw_text:
                known[_squash(c.number.raw_text)] = c.label
            if c.number.value:
                known[c.number.value] = c.label
    return known


def _label(c: RowCitationExtraction, known: dict[str, str], pages: PageText) -> str:
    """줄 안 인용의 라벨. 모델이 준 라벨이나 인용 원문을 거절이유 표의 라벨과 맞춘다."""
    if c.label:
        if c.label in set(known.values()):
            return c.label
        raise _Fail()
    raw = _squash(_need(c.number, pages))
    m = re.fullmatch(r"인용발명(\d+)", raw)  # OA 인용발명 N = DN
    if m and f"D{m.group(1)}" in known.values():
        return f"D{m.group(1)}"
    if raw in known:
        return known[raw]
    raise _Fail()


def _locations(c: RowCitationExtraction, pages: PageText) -> list[str]:
    """짚은 위치(원문에서 다시 읽음)와 위치 없음 표현을 정답 꼴 목록으로."""
    out: list[str] = []
    if c.location is not None:
        found = parse_cited_locations(_need(c.location, pages))
        if found is None:
            raise _Fail()  # 못 읽는 조각: 지어내지 않는다
        out += found
    if c.no_location is not None:
        expression = _need(c.no_location, pages).strip(_QUOTE_CHARS)
        out.append(f"{_NO_LOCATION} ({expression})")
    return out


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _mentioned(judgment: str, rej: dict) -> set[str]:
    """판단 원문이 가리키는 인용 라벨: `인용발명 N`(`1 내지 2`, `1, 2` 포함)과 인용 원문 표기."""
    text = _squash(judgment)
    found: set[str] = set()
    for m in re.finditer(r"인용발명(\d+(?:(?:내지|~|-|,|및|와|과)(?:인용발명)?\d+)*)", text):
        parts = re.split(r"(내지|~|-|,|및|와|과)", m.group(1))
        numbers, seps = parts[0::2], parts[1::2]
        found.add(f"D{int(numbers[0])}")
        for sep, num in zip(seps, numbers[1:], strict=True):
            lo = int(numbers[numbers.index(num) - 1]) if sep in ("내지", "~", "-") else int(num)
            found.update(f"D{n}" for n in range(lo, int(num) + 1))
    for c in rej["citations"]:
        if c.number.raw_text and _squash(c.number.raw_text) in text:
            found.add(c.label)
    return found


def _content(r: ClaimRowExtraction, kind: RejectionKind, rej: dict, pages: PageText) -> dict:
    """줄 안 값을 원문과 맞춰 뽑는다. 하나라도 못 맞추면 _Fail (그 줄을 통째로 버림)."""
    if _is_ambiguous(r):
        raise _Fail(UnverifiedReason.AMBIGUOUS)
    judgment = _need(r.judgment, pages)  # 이 줄 판단 원문이 그 쪽에 있어야 확인됨
    assert r.judgment is not None and r.judgment.page is not None
    same_as: list[str] = []
    for item in r.same_as:
        found = parse_same_as(_need(item, pages))
        if found is None:
            raise _Fail()
        same_as += found
    out: dict = {
        "raw_text": judgment,
        "page": r.judgment.page,
        "same_as": _unique(same_as),
        "citations": [],
        "locations": {},
        "clarity_terms": [],
        "clarity_reason": None,
    }
    if kind == RejectionKind.CLARITY:
        # 명확성 줄은 인용 대신 문제 표현: 따옴표 안 글자이고 원문에 있어야 함
        # (따옴표가 없으면 표현은 빈 목록, 3절 11)
        quoted = [_squash(q) for q in quoted_segments(judgment)]
        terms = [_need(t, pages).strip(_QUOTE_CHARS) for t in r.clarity_terms]
        if any(_squash(t) not in quoted for t in terms):
            raise _Fail()
        out["clarity_terms"] = _unique(terms)
        reason = (r.clarity_reason or "").strip()
        out["clarity_reason"] = reason or None
        out["clarity_reason_origin"] = Origin.AI_GENERATED if reason else None  # 모델이 쓴 글
        return out
    citations: list[str] = []
    locations: dict[str, list[str]] = {}
    known = _labels_of([rej])  # 후보는 그 거절이유의 인용문헌뿐
    mentioned = _mentioned(judgment, rej)
    for c in r.citations:
        label = _label(c, known, pages)
        # 판단 원문이 그 인용을 실제로 가리켜야 쓴다 (엉뚱한 인용이 붙지 않게)
        if label not in mentioned:
            raise _Fail()
        citations.append(label)
        found = _locations(c, pages)
        if found:
            locations[label] = _unique([*locations.get(label, []), *found])
    out["citations"] = _unique(citations)
    out["locations"] = locations
    return out


def _unverified(claim: int | None, rejection: int | None, reason: UnverifiedReason) -> ClaimRow:
    status = Status(value=StatusValue.UNVERIFIED, reason=reason)
    return ClaimRow(claim=claim, rejection=rejection, status=status)


def _head_number(judgment: Item, pages: PageText) -> int | None:
    """판단 원문 머리 번호(`N-M.`): 원문 글자 맨 앞, 없으면 그 쪽에서 바로 앞 글자."""
    raw = judgment.raw_text or ""
    m = re.match(r"\s*(\d+)\s*-\s*\d+\s*[.)]", raw)
    if m:
        return int(m.group(1))
    page = next((p for p in pages.pages if p.page == judgment.page), None)
    if page is None:
        return None
    text, needle = _squash(page.text), _squash(raw)
    at = text.find(needle)
    m = re.search(r"(?<!\d)(\d+)-\d+[.)]$", text[:at]) if at > 0 else None
    return int(m.group(1)) if m else None


def _fits(r: ClaimRowExtraction, rej: dict, pages: PageText) -> bool:
    """청구항 번호 원문이 판단 원문 안에 있고, 머리 번호가 있으면 거절이유 순번과 같은가."""
    if not _on_page(r.judgment, pages):
        return True  # 판단 원문이 없으면 값 대조에서 어차피 떨어진다
    assert r.judgment is not None and r.claims is not None
    if _squash(r.claims.raw_text or "") not in _squash(r.judgment.raw_text or ""):
        return False
    head = _head_number(r.judgment, pages)
    return head is None or head == rej["no"]


def _is_ambiguous(r: ClaimRowExtraction) -> bool:
    return any(i is not None and i.ambiguous for i in _all_items(r))


def build_claim_rows(
    rows: list[ClaimRowExtraction],
    rejections: list[dict],
    pages: PageText,
    parse_claims: Callable[[str], list[int] | None],
) -> list[ClaimRow]:
    """모델 줄들을 원문 대조해 ClaimRow 목록으로. 청구항이 묶여 있으면 번호마다 한 줄로 펼친다.

    rejections: read_oa가 만든 거절이유 칸 dict (no·article·supported·claims·citations).
    """
    by_no = {r["no"]: r for r in rejections}
    made: list[ClaimRow] = []
    seen: set[tuple[int, int]] = set()
    for r in rows:
        rej = by_no.get(r.rejection) if r.rejection is not None else None
        if rej is not None and not rej["supported"]:
            # 지원 안 하는 이유는 거절이유 표에만 두고 줄을 만들지 않는다 (3절 9)
            logger.info("지원 안 하는 거절이유 %s의 청구항 줄은 만들지 않음", r.rejection)
            continue
        if r.rejection is not None and rej is None:
            logger.warning("청구항 줄이 없는 거절이유 %s를 가리킴: 확인되지 않음", r.rejection)
        no = rej["no"] if rej is not None else None
        claims = parse_claims(r.claims.raw_text or "") if _on_page(r.claims, pages) else None

        if rej is not None and claims is not None and not _fits(r, rej, pages):
            # 청구항·순번이 판단 원문과 안 맞는 줄: 어느 줄인지 못 정해 번호 없이 남긴다
            reason = (
                UnverifiedReason.AMBIGUOUS if _is_ambiguous(r) else UnverifiedReason.NOT_EXTRACTED
            )
            made.append(_unverified(None, None, reason))
            continue

        # 값 대조는 줄 하나 단위라 청구항마다 같은 값을 준다 (3절 10)
        content: dict = {}
        reason: UnverifiedReason | None = None
        if rej is None or claims is None:  # 어느 줄인지 못 정함
            reason = (
                UnverifiedReason.AMBIGUOUS if _is_ambiguous(r) else UnverifiedReason.NOT_EXTRACTED
            )
        else:
            try:
                content = _content(r, kind_of_article(rej["article"].value), rej, pages)
            except _Fail as fail:
                reason = fail.reason

        targets = rej["claims"].value if rej is not None else None
        for claim in claims if claims is not None else [None]:
            if claim is not None and no is not None:
                if (claim, no) in seen:
                    logger.info("같은 청구항·거절이유 줄이 겹침: 앞의 것만 남김")
                    continue
                seen.add((claim, no))
            row_reason = reason
            if row_reason is None and targets is not None and claim not in targets:
                logger.warning("청구항 %s는 거절이유 %s의 대상이 아님: 확인되지 않음", claim, no)
                row_reason = UnverifiedReason.NOT_EXTRACTED
            if row_reason is not None:
                made.append(_unverified(claim, no, row_reason))
                continue
            status = Status(value=StatusValue.CONFIRMED, checked=f"{content['page']}쪽 원문 대조")
            made.append(ClaimRow(claim=claim, rejection=no, status=status, **content))
    # 지원하는 거절이유의 대상 청구항 중 줄이 없는 것은 빈 줄로 채운다
    # (줄이 빠져도 조용히 지나가지 않게)
    produced = {(row.claim, row.rejection) for row in made}
    for rej in rejections:
        if not rej["supported"] or rej["claims"].value is None:
            continue  # 대상 청구항을 모르면 채울 수 없다 (거절이유 status가 이미 확인되지 않음)
        for claim in rej["claims"].value:
            if (claim, rej["no"]) not in produced:
                logger.warning("청구항 %s 거절이유 %s: 모델이 줄을 주지 않음", claim, rej["no"])
                made.append(_unverified(claim, rej["no"], UnverifiedReason.NOT_EXTRACTED))
    return made
