"""판 문서 글자 → 청구항 번호별 원문 (이슈 #205 T1). 답이 정해진 코드 도구다 (모델 호출 없음).

- 출원서(출원 때 판): 【청구범위】 아래 【청구항 N】 머리 줄로 나눈다. 【요약서】에서 끝난다.
- 보정서: 바꾼 항목만 들어 있다 (【보정대상항목】 청구항 N / 【보정방법】 정정·추가·삭제).
  그래서 출원 때 판부터 보정서를 차례로 적용해 OA 당시 판을 만든다.
  보정서에 【보정대상항목】이 없고 청구항 묶음만 있으면 (따로 올린 보정 청구항) 통째로 바꾼다.
- 번호가 겹치거나 빠지거나, 보정 항목을 알아볼 수 없으면 지어내지 않고 unverified로 돌려준다.
  글자는 PDF 글자 층 그대로 둔다 (줄바꿈을 붙이거나 띄어 쓰지 않는다: 원래 띄어쓰기를 모른다).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from patent_ai.core.schemas.common import Status, StatusValue, UnverifiedReason

logger = logging.getLogger(__name__)

_CLAIM_HEAD = re.compile(r"【\s*청구항\s*(\d+)\s*】")
_CLAIMS_START = re.compile(r"【\s*청구범위\s*】")
# 청구범위 다음에 오는 구간 머리 줄 (여기서 청구항 글이 끝난다)
_CLAIMS_END = re.compile(r"【\s*(요약서|요약|도면|대표도|첨부서류)\s*】")
# 보정서 끝에 붙는 서류 머리 줄 (마지막 항목의 보정내용이 여기서 끝난다)
_TRAILER = re.compile(r"【\s*첨부서류\s*】")
_ITEM = re.compile(r"【\s*보정대상항목\s*】")
_METHOD = re.compile(r"【\s*보정방법\s*】")
_CONTENT = re.compile(r"【\s*보정내용\s*】")
_TARGET_CLAIM = re.compile(r"^청구항\s*(\d+)$")
_DELETED = "삭제"


@dataclass(frozen=True)
class ClaimTexts:
    """OA 당시 판의 청구항 글자와 그 상태. confirmed가 아니면 F3·F4 결과는 input_unverified."""

    claims: dict[int, str]
    status: Status


@dataclass
class _Parsed:
    """청구항 묶음 하나를 나눈 결과. deleted는 '삭제'라고만 적힌 번호 (번호는 차지한다)."""

    claims: dict[int, str] = field(default_factory=dict)
    deleted: set[int] = field(default_factory=set)
    problem: Status | None = None

    def last_number(self) -> int:
        """이 묶음에서 쓰인 가장 큰 번호 ('삭제'로 남은 번호도 센다). 비면 0."""
        return max(self.claims.keys() | self.deleted, default=0)


def _unverified(reason: UnverifiedReason) -> Status:
    return Status(value=StatusValue.UNVERIFIED, reason=reason)


def _split_claims(text: str) -> _Parsed:
    """【청구항 N】 머리 줄로 나눈다. 번호가 겹치거나 글이 비면 problem."""
    out = _Parsed()
    heads = list(_CLAIM_HEAD.finditer(text))
    for i, m in enumerate(heads):
        number = int(m.group(1))
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[m.end() : end].strip()
        if number in out.claims or number in out.deleted:
            logger.warning("claim_texts: 청구항 %d 번호가 겹침", number)
            out.problem = _unverified(UnverifiedReason.AMBIGUOUS)
            return out
        if body == _DELETED:
            out.deleted.add(number)
        elif not body:
            logger.warning("claim_texts: 청구항 %d 글이 비어 있음", number)
            out.problem = _unverified(UnverifiedReason.NOT_EXTRACTED)
            return out
        else:
            out.claims[number] = body
    return out


def _section_bounds(text: str) -> tuple[int, int] | None:
    """【청구범위】부터 요약서·도면 머리 줄 앞까지의 위치. 【청구범위】가 없으면 첫 청구항부터."""
    start = _CLAIMS_START.search(text)
    first = _CLAIM_HEAD.search(text)
    if first is None:
        return None
    begin = start.end() if start and start.start() <= first.start() else first.start()
    end = _CLAIMS_END.search(text, begin)
    return begin, end.start() if end else len(text)


def _claim_section(text: str) -> str:
    bounds = _section_bounds(text)
    return text[bounds[0] : bounds[1]] if bounds else ""


def _claim_items(text: str) -> list[tuple[int, int, str]]:
    """보정서의 항목마다 (시작, 끝, 대상 글자). 끝은 다음 항목 앞 또는 첨부서류 머리 줄 앞."""
    items = list(_ITEM.finditer(text))
    out = []
    for i, m in enumerate(items):
        end = items[i + 1].start() if i + 1 < len(items) else len(text)
        trailer = _TRAILER.search(text, m.end(), end)
        end = trailer.start() if trailer else end
        method_m = _METHOD.search(text, m.end(), end)
        target = text[m.end() : method_m.start() if method_m else end].strip()
        out.append((m.start(), end, target))
    return out


def claim_region(text: str, *, first: bool) -> tuple[int, int] | None:
    """이 모듈이 그 문서에서 청구항으로 읽는 글자 범위 (시작, 끝). 못 찾으면 None.

    부르는 쪽(texts_source)이 이 범위에 글자 층 없는 쪽이 끼었는지 보려고 쓴다.
    first=True는 출원 때 판 문서(청구항 묶음 전체), False는 보정서.
    """
    items = [] if first else _claim_items(text)
    if not items:
        return _section_bounds(text)
    claim_items = [(s, e) for s, e, target in items if target.startswith("청구")]
    if not claim_items:
        return None
    return claim_items[0][0], claim_items[-1][1]


def _parse_full_set(text: str) -> _Parsed:
    """청구항 묶음 전체 (출원서·통째로 바꾼 청구범위). 번호는 1부터 빠짐없이 이어져야 한다."""
    parsed = _split_claims(_claim_section(text))
    if parsed.problem:
        return parsed
    numbers = sorted(parsed.claims.keys() | parsed.deleted)
    if not parsed.claims:
        logger.warning("claim_texts: 청구항을 하나도 못 찾음")
        parsed.problem = _unverified(UnverifiedReason.NOT_EXTRACTED)
    elif numbers != list(range(1, len(numbers) + 1)):
        logger.warning("claim_texts: 청구항 번호가 빠짐 (%s)", numbers)
        parsed.problem = _unverified(UnverifiedReason.NOT_EXTRACTED)
    return parsed


def _apply_amendment(
    prev: dict[int, str], last: int, text: str
) -> tuple[dict[int, str], int, Status | None]:
    """보정서 하나를 앞 판에 적용한다. 돌려주는 것은 (새 판, 새 최대 번호, 문제 상태 또는 None).

    last는 앞 판까지 쓰인 가장 큰 청구항 번호다. 삭제된 청구항도 번호는 남으므로
    청구항 글이 없어진 뒤에도 last는 줄지 않는다 (추가 번호는 last + 1부터 이어져야 한다).
    """
    items = _claim_items(text)
    if not items:
        # 보정대상항목이 없으면 따로 올린 보정 청구항(청구항 묶음 전체)으로 본다
        whole = _parse_full_set(text)
        return whole.claims, whole.last_number(), whole.problem

    claims = dict(prev)
    base = last  # 이 보정서의 추가 번호가 이어 붙을 앞 번호
    added: list[int] = []  # 이 보정서가 추가한 청구항 번호
    touched = 0  # 청구항을 건드린 항목 수 (0이면 이 판의 청구항을 읽지 못한 것)
    bad = _unverified(UnverifiedReason.NOT_EXTRACTED)
    for start, end, target in items:
        block = text[start:end]
        method_m = _METHOD.search(block)
        if not target.startswith("청구"):
            continue  # 표지("별지와 같음")·식별번호·도면 같은 다른 항목
        if method_m is None:
            logger.warning("claim_texts: 보정방법이 없는 항목 (%s)", target)
            return claims, last, bad
        content_m = _CONTENT.search(block, method_m.end())
        method = block[method_m.end() : content_m.start() if content_m else len(block)].strip()
        content = block[content_m.end() :] if content_m else ""
        touched += 1

        if target == "청구범위":
            if method != "정정":
                logger.warning("claim_texts: 청구범위 보정방법을 모름 (%s)", method)
                return claims, last, bad
            whole = _parse_full_set(content)
            if whole.problem:
                return claims, last, whole.problem
            claims = whole.claims
            # 청구범위를 통째로 바꾸면 번호도 새로 센다
            base, added = whole.last_number(), []
            continue

        number_m = _TARGET_CLAIM.match(target)
        if number_m is None:
            logger.warning("claim_texts: 보정대상항목을 알아볼 수 없음 (%s)", target)
            return claims, last, bad
        number = int(number_m.group(1))
        # 삭제·정정은 앞 판에 있는 번호만, 추가는 없는 번호만 (덮어쓰거나 번호가 비지 않게)
        if method in ("삭제", "정정") and number not in claims:
            logger.warning("claim_texts: 앞 판에 없는 청구항 %d을 %s함", number, method)
            return claims, last, bad
        if method == "추가" and number in claims:
            logger.warning("claim_texts: 앞 판에 이미 있는 청구항 %d을 추가함", number)
            return claims, last, bad
        if method == "삭제":
            del claims[number]
        elif method in ("정정", "추가"):
            parsed = _split_claims(content)
            if parsed.problem:
                return claims, last, parsed.problem
            if number in parsed.deleted and not parsed.claims:
                claims.pop(number, None)  # 정정 내용이 '삭제'라고만 적힘
                continue
            if set(parsed.claims) != {number}:
                logger.warning("claim_texts: 청구항 %d 보정내용 번호가 다름", number)
                return claims, last, bad
            claims[number] = parsed.claims[number]
            if method == "추가":
                added.append(number)
        else:
            logger.warning("claim_texts: 보정방법을 모름 (%s)", method)
            return claims, last, bad

    if touched == 0:
        logger.warning("claim_texts: 보정서에 청구항 항목이 없음")
        return claims, last, bad
    # 추가 번호는 앞 최대 번호 + 1부터 빈틈없이 (예: 앞 판 1~2면 3, 4…).
    # 건너뛰면 번호를 잘못 읽은 것으로 보고 확정하지 않는다
    expected = list(range(base + 1, base + 1 + len(added)))
    if sorted(added) != expected:
        logger.warning("claim_texts: 추가 청구항 번호 %s가 %d 다음부터 이어지지 않음", added, base)
        return claims, last, bad
    return claims, base + len(added), None


def claims_at_version(documents: list[str]) -> ClaimTexts:
    """판 문서 글자 목록 → 그 마지막 판의 청구항.

    documents[0]은 출원 때 판 문서(출원서), 뒤는 그 판까지의 보정서를 순서대로.
    각 글자는 그 문서 쪽 글자를 줄바꿈으로 이은 것이다.
    """
    if not documents:
        logger.warning("claim_texts: 판 문서가 0개")
        return ClaimTexts({}, _unverified(UnverifiedReason.BODY_MISSING))
    first = _parse_full_set(documents[0])
    if first.problem:
        return ClaimTexts(first.claims, first.problem)
    claims = first.claims
    last = first.last_number()
    for text in documents[1:]:
        claims, last, problem = _apply_amendment(claims, last, text)
        if problem:
            return ClaimTexts(claims, problem)
    if not claims:
        logger.warning("claim_texts: 보정을 적용하니 청구항이 0개")
        return ClaimTexts({}, _unverified(UnverifiedReason.NOT_EXTRACTED))
    amendments = len(documents) - 1
    checked = f"출원서 + 보정서 {amendments}개를 적용해 청구항 {len(claims)}개"
    return ClaimTexts(claims, Status(value=StatusValue.CONFIRMED, checked=checked))
