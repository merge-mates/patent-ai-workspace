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
from patent_ai.core.f1_oa_reader.rules import (
    claims_mentioned,
    parse_cited_locations,
    parse_same_as,
    quoted_segments,
)
from patent_ai.core.f1_oa_reader.verify import raw_text_on_page
from patent_ai.core.schemas.common import Origin, Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.document import PageText
from patent_ai.core.schemas.oa_result import ClaimRow, RejectionKind, kind_of_article

logger = logging.getLogger(__name__)

_QUOTE_CHARS = " '\"‘’“”「」『』"
_NO_LOCATION = "위치 없음"

# 인용을 정한 규칙 (정답 형식 3절 12번 순서). 확인됨 근거(checked)에 붙는 문구
_BY_MENTION = "mentioned"  # 1) 판단 원문에 적힌 인용발명
_BY_SAME_AS = "same_as"  # 2) 같은 취지 대상 줄의 인용 (줄을 다 만든 뒤 두 번째 단계에서 푼다)
_BY_ALL = "all"  # 3) 그 거절이유에 쓰인 인용 전부
_RULE_NOTE = {
    _BY_SAME_AS: "문장에 인용 표기 없음, 같은 취지 대상 줄의 인용으로 봄",
    _BY_ALL: "문장에 인용 표기 없음, 거절이유 인용 전부로 봄",
}
# _content가 돌려주는 dict에서 ClaimRow 칸이 아닌 것
_INTERNAL = ("citation_rule", "location_ambiguous")


class _Fail(Exception):
    """줄의 값을 원문과 못 맞췄다. 이유는 status.reason, 떨어진 검사는 detail(사람이 보는 글)."""

    def __init__(
        self,
        reason: UnverifiedReason = UnverifiedReason.NOT_EXTRACTED,
        detail: str = "원문 글자를 그 쪽에서 못 찾음",
    ):
        self.reason = reason
        self.detail = detail


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


def _need_in(item: Item | None, pages: PageText, judgment: str) -> str:
    """판단 원문 안 칸(위치·같은 취지 등)의 원문 글자. 그 칸 쪽에 있거나, 대조를 통과한
    판단 원문 안에 있으면 통과 (판단이 다음 쪽까지 걸쳐 칸 쪽 번호가 시작 쪽과 다를 때)."""
    if item is not None and item.raw_text and not _on_page(item, pages):
        if _squash(item.raw_text) and _squash(item.raw_text) in _squash(judgment):
            return item.raw_text
    return _need(item, pages)


def _has_bare_string(r: ClaimRowExtraction) -> bool:
    """목록 칸에 Item 대신 문자열이 있나 (재시도 답에서만 들어올 수 있음, 원문·쪽이 없음)."""
    return any(isinstance(i, str) for i in [*r.same_as, *r.clarity_terms])


def _all_items(r: ClaimRowExtraction) -> list[Item | None]:
    items: list[Item | None] = [r.claims, r.judgment, r.no_location]
    items += [i for i in [*r.same_as, *r.clarity_terms] if isinstance(i, Item)]
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
        raise _Fail(detail="인용 라벨이 거절이유 표에 없음")
    raw = _squash(_need(c.number, pages))
    m = re.fullmatch(r"인용발명(\d+)", raw)  # OA 인용발명 N = DN
    if m and f"D{m.group(1)}" in known.values():
        return f"D{m.group(1)}"
    if raw in known:
        return known[raw]
    raise _Fail(detail="인용 번호를 거절이유 표와 못 맞춤")


def _location_text(item: Item, pages: PageText, judgment: str) -> str:
    """위치 칸 원문 글자. 모델이 두 곳 위치를 ';'로 이어 줬으면 조각마다 대조한다 (조각이 다
    원문에 있어야 통과, 하나라도 없으면 _Fail)."""
    raw = item.raw_text or ""
    whole_ok = _on_page(item, pages) or (_squash(raw) and _squash(raw) in _squash(judgment))
    if whole_ok or ";" not in raw:
        return _need_in(item, pages, judgment)
    for part in raw.split(";"):
        _need_in(item.model_copy(update={"raw_text": part.strip()}), pages, judgment)
    return raw


def _locations(c: RowCitationExtraction, pages: PageText, judgment: str = "") -> list[str]:
    """짚은 위치(원문에서 다시 읽음)와 위치 없음 표현을 정답 꼴 목록으로."""
    out: list[str] = []
    if c.location is not None:
        found = parse_cited_locations(_location_text(c.location, pages, judgment))
        if found is None:  # 못 읽는 조각: 지어내지 않는다
            raise _Fail(detail="위치 글자를 정답 꼴로 못 읽음")
        out += found
    if c.no_location is not None:
        expression = _need_in(c.no_location, pages, judgment).strip(_QUOTE_CHARS)
        out.append(f"{_NO_LOCATION} ({expression})")
    return out


def _inside(item: Item, judgment: str) -> bool:
    """원문 글자가 그 줄 판단 원문 안에 있나 (공백 무시). ';'로 이은 위치는 조각마다 본다."""
    parts = [p for p in (item.raw_text or "").split(";") if p.strip()] or [""]
    return all(_squash(p) in _squash(judgment) for p in parts)


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
    if _has_bare_string(r):
        # 원문·쪽 없는 문자열은 대조할 수 없다: 그 줄을 확인되지 않음으로 (확인됨으로 새지 않게)
        logger.warning("청구항 줄 목록 칸에 원문·쪽 없는 문자열: 그 줄은 확인되지 않음")
        raise _Fail(detail="목록 칸에 원문·쪽 없는 글자")
    if _is_ambiguous(r):
        raise _Fail(UnverifiedReason.AMBIGUOUS, "모델이 애매 표시를 붙임")
    judgment = _need(r.judgment, pages)  # 이 줄 판단 원문이 그 쪽에 있어야 확인됨
    assert r.judgment is not None and r.judgment.page is not None
    same_as: list[str] = []
    for item in r.same_as:
        found = parse_same_as(_need_in(item, pages, judgment))
        if found is None:
            raise _Fail(detail="같은 취지 대상을 못 읽음")
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
        terms = [_need_in(t, pages, judgment).strip(_QUOTE_CHARS) for t in r.clarity_terms]
        if any(_squash(t) not in quoted for t in terms):
            raise _Fail(detail="문제 표현이 판단 원문 따옴표 안에 없음")
        if r.no_location is not None:
            logger.warning("명확성 줄의 줄 단위 위치 없음은 쓰지 않음")
        out["clarity_terms"] = _unique(terms)
        reason = (r.clarity_reason or "").strip()
        out["clarity_reason"] = reason or None
        out["clarity_reason_origin"] = Origin.AI_GENERATED if reason else None  # 모델이 쓴 글
        return out
    locations: dict[str, list[str]] = {}
    known = _labels_of([rej])  # 후보는 그 거절이유의 인용문헌뿐
    allowed = [c.label for c in rej["citations"]]
    mentioned = _mentioned(judgment, rej)
    if mentioned - set(allowed):  # 판단 원문이 그 거절이유 밖의 인용을 가리킴
        raise _Fail(detail="판단 원문이 거절이유 밖 인용을 가리킴")
    # 인용은 모델이 고르지 않고 3절 12번 순서로 정한다
    if mentioned:  # 1) 판단 원문에 적힌 문헌 (거절이유 인용 표 순서)
        rule, citations = _BY_MENTION, [label for label in allowed if label in mentioned]
    elif out["same_as"]:  # 2) 같은 취지 대상 줄의 인용: 줄을 다 만든 뒤 푼다
        rule, citations = _BY_SAME_AS, []
    else:  # 3) 그 거절이유에 쓰인 인용 전부
        rule, citations = _BY_ALL, list(allowed)
        if not allowed:
            logger.warning("인용 언급도 같은 취지도 없는데 거절이유 %s에 인용이 없음", rej["no"])
    # 위치는 원문이 정한다: 모델이 짚은 위치가 어느 문헌의 것인지 원문으로 정해져야 확인됨
    candidates = citations if mentioned else allowed
    location_ambiguous = False
    for c in r.citations:
        if c.label or c.number is not None:
            label: str | None = _label(c, known, pages)  # 거절이유 밖 라벨이면 _Fail
        else:
            label = candidates[0] if len(candidates) == 1 else None  # 후보가 하나뿐이면 그것
        has_location = c.location is not None or c.no_location is not None
        if label is None:
            if has_location:
                # 위치가 있는데 어느 인용인지 모름
                raise _Fail(UnverifiedReason.AMBIGUOUS, "위치가 어느 인용의 것인지 모름")
            continue
        if mentioned and label not in mentioned:  # 판단 원문이 가리키는 인용과 다름
            raise _Fail(detail="모델 인용이 판단 원문이 가리키는 인용과 다름")
        if has_location and not mentioned and len(allowed) > 1:
            # 언급 없이 인용이 여럿: 모델 라벨 아래 위치를 남기되 원문으로 못 정했으니 애매
            location_ambiguous = True
        if c.location is not None and not _inside(c.location, judgment):
            # 위치 글자가 이 줄 판단 원문 밖 (예: 묶은 결론 문장 + 다른 항 문단의 위치):
            # 통지서가 이 항에 짚은 위치인지 원문으로 못 정함 -> 값은 남기되 애매 (이슈 #161)
            location_ambiguous = True
        found = _locations(c, pages, judgment)
        if found:
            locations[label] = _unique([*locations.get(label, []), *found])
    out["citation_rule"] = rule
    out["location_ambiguous"] = location_ambiguous
    if r.no_location is not None and rule == _BY_SAME_AS:
        # 인용이 아직 안 정해진 줄이라 줄 단위 위치 없음을 어느 인용 아래 둘지 못 정함
        raise _Fail(UnverifiedReason.AMBIGUOUS, "위치 없음을 어느 인용에 둘지 모름")
    if r.no_location is not None:
        # 인용이 하나도 없는 줄의 위치 없음: 표현이 이 줄 판단 원문 안에 있어야 한다
        expression = _need_in(r.no_location, pages, judgment).strip(_QUOTE_CHARS)
        if not expression or _squash(expression) not in _squash(judgment):
            raise _Fail(detail="위치 없음 표현이 판단 원문 밖")
        text = f"{_NO_LOCATION} ({expression})"
        unique = _unique(citations)
        if not unique:
            out["no_location"] = text
        elif len(unique) == 1 and unique[0] not in locations:
            locations[unique[0]] = [text]  # 인용이 하나고 위치가 없으면 그 인용의 위치로 옮긴다
        else:  # 어느 인용의 위치 없음인지 못 정함
            raise _Fail(UnverifiedReason.AMBIGUOUS, "위치 없음을 어느 인용에 둘지 모름")
    out["citations"] = _unique(citations)
    out["locations"] = locations
    return out


def _model_values(r: ClaimRowExtraction, rej: dict, kind: RejectionKind) -> dict:
    """대조에 떨어진 줄에 남길 모델 값 (확인 안 됨). 판단 원문·쪽·인용·위치·같은 취지·문제 표현.

    값을 지어내지 않는다: 모델이 준 글자만 옮기고, 읽히면 정답 꼴로, 안 읽히면 글자 그대로 둔다.
    인용 라벨은 그 거절이유 인용 표에 있는 것만 (밖의 라벨은 버린다).
    """
    out: dict = {"citations": [], "locations": {}, "same_as": [], "clarity_terms": []}
    if r.judgment is not None and r.judgment.raw_text and r.judgment.raw_text.strip():
        out["raw_text"] = r.judgment.raw_text
        out["page"] = r.judgment.page
    allowed = {c.label for c in rej["citations"]}
    for item in r.same_as:
        if isinstance(item, Item) and item.raw_text:
            out["same_as"] += parse_same_as(item.raw_text) or []
    if kind == RejectionKind.CLARITY:
        out["clarity_terms"] = _unique(
            [
                t.raw_text.strip(_QUOTE_CHARS)
                for t in r.clarity_terms
                if isinstance(t, Item) and t.raw_text
            ]
        )
        return out
    for c in r.citations:
        label = c.label if c.label in allowed else None
        if label is None:
            continue
        out["citations"].append(label)
        if c.location is not None and c.location.raw_text:
            raw = c.location.raw_text
            found = parse_cited_locations(raw) or [raw.strip()]
            out["locations"][label] = _unique([*out["locations"].get(label, []), *found])
    out["citations"] = _unique(out["citations"])
    out["same_as"] = _unique(out["same_as"])
    return out


def _unverified(
    claim: int | None,
    rejection: int | None,
    reason: UnverifiedReason,
    *,
    values: dict | None = None,
    check_failed: str | None = None,
) -> ClaimRow:
    """확인되지 않음 줄. values·check_failed가 있으면 모델 값을 떨어진 검사와 함께 남긴다 (D3)."""
    status = Status(value=StatusValue.UNVERIFIED, reason=reason)
    if values and check_failed and claim is not None and rejection is not None:
        return ClaimRow(
            claim=claim, rejection=rejection, status=status, check_failed=check_failed, **values
        )
    return ClaimRow(claim=claim, rejection=rejection, status=status)


def _label_order(label: str) -> tuple[int, str]:
    """`D2`가 `D10`보다 앞에 오게 번호로 정렬한다."""
    m = re.fullmatch(r"D(\d+)", label)
    return (int(m.group(1)), "") if m else (10**9, label)


def _target_key(row: ClaimRow, target: str) -> tuple[int | None, int | None]:
    """같은 취지 대상 -> 가리키는 줄 (청구항, 거절이유).

    `claim:N` = 같은 거절이유의 청구항 N 줄, `rejection:N` = 같은 청구항의 거절이유 N 줄.
    """
    kind, _, number = target.partition(":")
    if kind == "claim":
        return int(number), row.rejection
    return row.claim, int(number)


def _resolve_same_as(
    made: list[ClaimRow],
    pending: dict[int, dict[str, list[str]]],
    cite_ok: set[int] | None = None,
) -> list[ClaimRow]:
    """규칙 2: 같은 취지 줄의 인용 = 대상 줄 인용의 합 (중복 빼고 라벨 순).

    대상 줄이 없거나(지원 안 하는 거절이유·대상 밖 청구항), 확인되지 않음이거나,
    같은 취지가 돌아서 제자리로 오면(순환) 그 줄도 확인되지 않음 (지어내지 않는다).
    pending: 줄 번호 -> 그 줄이 짚은 위치. 위치는 인용을 채운 뒤에 붙인다 (라벨이 인용 안이어야 함).
    """
    cite_ok = cite_ok or set()
    index = {(row.claim, row.rejection): i for i, row in enumerate(made)}

    def cites_known(j: int) -> bool:
        """줄 j의 인용을 원문으로 정했나: 확인됨이거나, 인용은 원문 규칙으로 정하고 위치만 애매."""
        return made[j].status.value == StatusValue.CONFIRMED or j in cite_ok

    done: dict[int, list[str] | None] = {}  # 줄 번호 -> 정한 인용 (못 정하면 None)

    def citations_of(i: int, path: frozenset[int]) -> list[str] | None:
        """줄 i의 인용. pending 줄이면 대상을 따라가 푼다."""
        if i in done:
            return done[i]
        row = made[i]
        if i not in pending:
            return row.citations if cites_known(i) else None
        merged: list[str] = []
        for target in row.same_as:
            j = index.get(_target_key(row, target))
            if j is None:
                logger.warning("같은 취지 대상 줄이 없음 (%s): 그 줄은 확인되지 않음", target)
                done[i] = None
                return None
            if j == i or j in path:
                logger.warning("같은 취지가 순환함 (%s): 그 줄은 확인되지 않음", target)
                done[i] = None
                return None
            found = citations_of(j, path | {i})
            # 대상 줄이 pending이면 그 줄 자신도 확인됨이어야 인용을 넘겨받는다
            if found is None or not cites_known(j):
                logger.warning(
                    "같은 취지 대상 줄 %s이 확인되지 않음: 그 줄도 확인되지 않음", target
                )
                done[i] = None
                return None
            merged += found
        if not merged:
            logger.warning("같은 취지 대상 줄의 인용이 비어 있음 (청구항 %s)", row.claim)
        done[i] = sorted(set(merged), key=_label_order)
        return done[i]

    out = list(made)
    for i in sorted(pending):
        citations = citations_of(i, frozenset())
        row = made[i]
        locations = pending[i]
        if citations is None:
            # 대상 줄 인용을 원문으로 못 정함: 이 줄 자신의 원문·쪽·같은 취지는 남긴다 (D3)
            own = row.model_dump(include={"raw_text", "page", "same_as"})
            out[i] = _unverified(
                row.claim,
                row.rejection,
                UnverifiedReason.NOT_EXTRACTED,
                values=own,
                check_failed="같은 취지 대상 줄의 인용을 원문으로 못 정함",
            )
        elif set(locations) - set(citations):
            # 짚은 위치의 라벨이 채운 인용 밖: 어느 인용의 위치인지 원문으로 못 정함 (값 비움)
            logger.warning("같은 취지 줄의 위치 라벨이 채운 인용 밖 (청구항 %s): 애매", row.claim)
            out[i] = _unverified(row.claim, row.rejection, UnverifiedReason.AMBIGUOUS)
        else:
            # model_copy는 검사를 다시 안 돌아서 새로 만들어 스키마 검사를 탄다
            data = row.model_dump()
            data.update(citations=citations, locations=locations)
            out[i] = ClaimRow.model_validate(data)
    return out


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
    # 공백을 없앤 쪽 글자라 쪽 머리 출원번호(…0162238) 뒤에 '2-3.'이 붙어 읽힐 수 있다.
    # 머리 번호(거절이유 순번)는 두 자리까지만 보고, 앞이 숫자면 머리 번호가 아니다 (11/26 P4)
    m = re.search(r"(?<!\d)(\d{1,2})-\d{1,3}[.)]$", text[:at]) if at > 0 else None
    return int(m.group(1)) if m else None


def _numbers_in_judgment(claims: list[int] | None, judgment: Item | None) -> bool:
    """청구항 번호가 모두 판단 원문에 '청구항 N'·'제N항' 꼴로 나오나."""
    if not claims or judgment is None:
        return False
    return set(claims) <= claims_mentioned(judgment.raw_text or "")


def _claims_just_before(r: ClaimRowExtraction, pages: PageText) -> bool:
    """청구항 글자가 같은 쪽에서 판단 원문 바로 앞 문장에 있나.

    모델이 "제1항에는 '…'가 기재되어 있습니다. 상기 기재에서 …"의 둘째 문장부터를 판단 원문으로
    줬다 (11/26 case08). 두 문장 넘어 앞이면 아님.
    """
    assert r.judgment is not None and r.claims is not None
    page = next((p for p in pages.pages if p.page == r.judgment.page), None)
    needle = _squash(r.claims.raw_text or "")
    if page is None or not needle:
        return False
    text = _squash(page.text)
    at = text.find(_squash(r.judgment.raw_text or ""))
    if at <= 0:
        return False
    pos = text.rfind(needle, 0, at)
    # 청구항 글자와 판단 원문 사이에 문장 끝이 하나까지 (그 청구항 문장이 끝나고 판단 원문이 시작)
    return pos >= 0 and len(re.findall(r"(다|요)\.", text[pos:at])) <= 1


def _fits(
    r: ClaimRowExtraction,
    rej: dict,
    pages: PageText,
    claims: list[int] | None = None,
) -> bool:
    """청구항 번호가 판단 원문 안에 있고, 머리 번호가 있으면 거절이유 순번과 같은가.

    청구항 글자가 판단 원문에 그대로 없어도('제1항' / 원문 '청구항 1 발명') 번호가 판단 원문에
    나오면 맞는 것으로 본다 (11/26 P4 원인 표). 번호는 원문 대조를 통과한 판단 글자에서 본다.
    """
    if not _on_page(r.judgment, pages):
        return True  # 판단 원문이 없으면 값 대조에서 어차피 떨어진다
    assert r.judgment is not None and r.claims is not None
    if _squash(r.claims.raw_text or "") not in _squash(r.judgment.raw_text or ""):
        if not _numbers_in_judgment(claims, r.judgment) and not _claims_just_before(r, pages):
            return False
    head = _head_number(r.judgment, pages)
    return head is None or head == rej["no"]


def _outside_parentheses(
    raw: str, parse_claims: Callable[[str], list[int] | None]
) -> list[int] | None:
    """괄호 안(인용항 등)을 뺀 나머지 글자의 청구항 번호. 괄호가 없거나 못 읽으면 None."""
    if "(" not in raw:
        return None
    outside = re.sub(r"\([^)]*\)", "", raw)
    return parse_claims(outside) if outside.strip() else None


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
    # 같은 취지 대상 줄로 인용을 정할 줄 (made 안 번호) -> 그 줄이 짚은 위치.
    # 인용이 아직 비어 있어 위치는 ClaimRow에 넣지 않고 따로 들고 있다가 인용을 채운 뒤 붙인다
    pending: dict[int, dict[str, list[str]]] = {}
    fallback: list[tuple[int, int, UnverifiedReason]] = []  # 값 없이 남길 줄 (다른 줄이 없을 때만)
    seen: dict[tuple[int, int], int] = {}  # (청구항, 거절이유) -> made 안 번호
    # 위치만 애매한 줄 (made 안 번호): 인용은 판단 원문 규칙으로 정해져 있어
    # 같은 취지 줄이 물려받을 수 있다
    cite_ok: set[int] = set()
    for r in rows:
        rej = by_no.get(r.rejection) if r.rejection is not None else None
        if rej is not None and not rej["supported"]:
            # 지원 안 하는 이유는 거절이유 표에만 두고 줄을 만들지 않는다 (3절 9)
            logger.info("지원 안 하는 거절이유 %s의 청구항 줄은 만들지 않음", r.rejection)
            continue
        if r.rejection is not None and rej is None:
            logger.warning("청구항 줄이 없는 거절이유 %s를 가리킴: 확인되지 않음", r.rejection)
        no = rej["no"] if rej is not None else None
        # 번호는 원문 대조를 통과한 청구항 원문 글자에서만 코드 규칙으로 읽는다 (모델 value 안 씀)
        raw = r.claims.raw_text or "" if _on_page(r.claims, pages) else ""
        claims = parse_claims(raw) if raw else None
        if not raw and r.claims is not None and r.claims.raw_text and _on_page(r.judgment, pages):
            # 모델이 청구항 글자를 바꿔 써('청구항 1' -> '제1항') 쪽에 없을 때: 번호가 대조를
            # 통과한 판단 원문에 다 나오면 그 번호로 줄을 만든다 (번호는 원문에 있다)
            guess = parse_claims(r.claims.raw_text)
            if _numbers_in_judgment(guess, r.judgment):
                raw, claims = r.claims.raw_text, guess

        if claims is None:
            cited = _outside_parentheses(raw, parse_claims) if raw else None
            if cited and no is not None:
                # "제9항(제6항 인용)"처럼 괄호 밖 번호만 읽히면 그 번호 줄을 애매로 남긴다.
                # 확인됨은 금지. 같은 청구항의 다른 줄이 있으면 그 줄이 먼저 (끝에서 빈자리만 채움)
                logger.warning("청구항 원문에 괄호가 있어 애매: 거절이유 %s", no)
                targets = rej["claims"].value if rej is not None else None
                # 대상 밖 청구항 줄은 만들지 않는다 (위 규칙과 같음)
                fallback += [
                    (c, no, UnverifiedReason.AMBIGUOUS) for c in cited if targets and c in targets
                ]
                continue
            # 번호 없는 줄은 만들지 않는다 (그 청구항은 끝에서 번호 있는 빈 줄로 채워짐)
            logger.warning("청구항 번호를 못 읽은 줄은 만들지 않음 (거절이유 %s)", no)
            continue
        if rej is not None and not _fits(r, rej, pages, claims):
            # 대상 청구항이면 끝에서 번호 있는 빈 줄로 채워진다 (대상 밖 청구항 줄은 만들지 않음)
            logger.warning("청구항·순번이 판단 원문과 안 맞는 줄은 번호 없이 만들지 않음")
            continue

        # 값 대조는 줄 하나 단위라 청구항마다 같은 값을 준다 (3절 10)
        content: dict = {}
        reason: UnverifiedReason | None = None
        failed: str | None = None  # 값 대조에 떨어진 검사 (D3: 모델 값을 남김)
        raw_values: dict = {}
        if rej is None:  # 어느 거절이유인지 못 정함
            reason = (
                UnverifiedReason.AMBIGUOUS if _is_ambiguous(r) else UnverifiedReason.NOT_EXTRACTED
            )
        else:
            kind = kind_of_article(rej["article"].value)
            try:
                content = _content(r, kind, rej, pages)
            except _Fail as fail:
                reason, failed = fail.reason, fail.detail
                raw_values = _model_values(r, rej, kind)

        targets = rej["claims"].value if rej is not None else None
        for claim in claims:
            if claim is not None and no is not None:
                if (claim, no) in seen:
                    # 앞 줄이 확인되지 않음이고 이 줄이 확인되면 이 줄로 바꾼다. 그 밖엔 앞의 것만.
                    # (case08: 같은 취지가 애매한 '2 내지 7항' 줄 뒤에 표현이 있는 '제7 및 14항' 줄)
                    at = seen[(claim, no)]
                    if made[at].status.value == StatusValue.CONFIRMED or reason is not None:
                        logger.info("같은 청구항·거절이유 줄이 겹침: 앞의 것만 남김")
                        continue
                    logger.info("겹친 줄: 앞 줄이 확인되지 않음이라 확인된 뒤 줄로 바꿈")
                    replace_at = at
                else:
                    replace_at = None
                    seen[(claim, no)] = len(made)
            else:
                replace_at = None
            row_reason = reason
            if row_reason is None and targets is not None and claim not in targets:
                logger.warning("청구항 %s는 거절이유 %s의 대상이 아님: 확인되지 않음", claim, no)
                row_reason = UnverifiedReason.NOT_EXTRACTED
            ambiguous_loc = content.get("location_ambiguous")
            if replace_at is not None and (row_reason is not None or ambiguous_loc):
                continue  # 확인된 줄로만 바꾼다
            if row_reason is not None:
                # 값 대조에 떨어진 줄만 모델 값을 남긴다 (대상 밖 청구항 줄은 번호만)
                keep = row_reason == reason and failed is not None
                made.append(
                    _unverified(
                        claim,
                        no,
                        row_reason,
                        values=raw_values if keep else None,
                        check_failed=failed if keep else None,
                    )
                )
                continue
            values = {k: v for k, v in content.items() if k not in _INTERNAL}
            rule = content.get("citation_rule")
            idx = len(made) if replace_at is None else replace_at
            if content.get("location_ambiguous"):
                cite_ok.add(idx)  # 인용은 원문 규칙으로 정했고 위치만 애매
                # 판단 원문에 인용 언급이 없고 인용이 여럿인데 모델이 위치를 짚음: 값은 남기되
                # 어느 문헌의 위치인지 원문으로 못 정했으니 확인되지 않음(애매)
                status = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.AMBIGUOUS)
            else:
                checked = f"{content['page']}쪽 원문 대조"
                if rule in _RULE_NOTE:
                    checked += f", {_RULE_NOTE[rule]}"
                status = Status(value=StatusValue.CONFIRMED, checked=checked)
            if rule == _BY_SAME_AS:
                pending[idx] = values.pop("locations")
            row = ClaimRow(claim=claim, rejection=no, status=status, **values)
            if replace_at is None:
                made.append(row)
            else:
                cite_ok.discard(replace_at)  # 앞 줄(확인되지 않음)의 표시는 버린다
                made[replace_at] = row
    # 지원하는 거절이유의 대상 청구항 중 줄이 없는 것은 빈 줄로 채운다
    # (줄이 빠져도 조용히 지나가지 않게)
    produced = {(row.claim, row.rejection) for row in made}
    for claim, no, reason in fallback:
        if (claim, no) not in produced:
            made.append(_unverified(claim, no, reason))
            produced.add((claim, no))
    for rej in rejections:
        if not rej["supported"] or rej["claims"].value is None:
            continue  # 대상 청구항을 모르면 채울 수 없다 (거절이유 status가 이미 확인되지 않음)
        for claim in rej["claims"].value:
            if (claim, rej["no"]) not in produced:
                logger.warning("청구항 %s 거절이유 %s: 모델이 줄을 주지 않음", claim, rej["no"])
                made.append(_unverified(claim, rej["no"], UnverifiedReason.NOT_EXTRACTED))
    # 같은 취지 줄의 인용은 빈 줄까지 다 만든 뒤 대상 줄에서 푼다 (3절 12번 2)
    return _resolve_same_as(made, pending, cite_ok)
