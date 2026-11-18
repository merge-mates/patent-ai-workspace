"""통지서 글자에서 규칙(정규식)으로 뽑는 것: 번호·날짜 글자·조문·청구항 범위·통지 종류.

모양의 기준은 docs/features/F1/design.md 2절 ③과 필드 출처 표.
못 찾거나 애매하면 None을 돌려준다 (값을 지어내지 않는다).
"""

import re
from dataclasses import dataclass

from patent_ai.core.schemas.common import ExtractedValue, Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.document import PageText
from patent_ai.core.schemas.oa_result import NoticeKind

# [가정] 1쪽 머리말 = 1쪽 글자의 첫 15줄. 표본 OA로 확인 (#22).
HEADER_LINES = 15


@dataclass(frozen=True)
class RuleCandidate:
    """규칙이 뽑은 값 하나. (schemas.common.Candidate와 이름이 겹쳐 RuleCandidate)

    날짜는 value를 비우고 raw_text(원문 글자 그대로)만 둔다.
    ambiguous: 같은 칸에 서로 다른 값이 둘 이상 보여 첫 값만 둔 경우.
    """

    value: str | None
    raw_text: str
    page: int
    ambiguous: bool = False


@dataclass(frozen=True)
class RuleFields:
    application_number: RuleCandidate | None = None
    dispatch_number: RuleCandidate | None = None
    notice_date: RuleCandidate | None = None
    response_due: RuleCandidate | None = None


# [가정] 형식: 출원번호 10-YYYY-NNNNNNN, 발송번호 9-5-YYYY-NNNNNNNNN (하이픈은 있어도 없어도),
# 날짜 YYYY.MM.DD. 이름표(출원번호·발송일자 등) 바로 뒤의 값만 뽑는다.
# 인용문헌의 번호를 출원번호로 잘못 뽑지 않으려는 것이다.
_GAP = r"[^\d\n]{0,8}"  # 이름표와 값 사이의 짧은 글자(공백·콜론 등)
_APP_NO = re.compile(r"출원번호" + _GAP + r"(10-?\d{4}-?\d{7})(?!\d)")
_DISPATCH_NO = re.compile(r"발송번호" + _GAP + r"(9-?5-?\d{4}-?\d{9})(?!\d)")
_DATE = r"(\d{4}\.\s?\d{1,2}\.\s?\d{1,2}\.)"
_NOTICE_DATE = re.compile(r"(?:발송일자|발송일|통지일)" + _GAP + _DATE)
_RESPONSE_DUE = re.compile(r"(?:제출기일|제출기한)" + _GAP + _DATE)


def _hyphenate_app(raw: str) -> str:
    d = raw.replace("-", "")
    return f"{d[:2]}-{d[2:6]}-{d[6:]}"


def _hyphenate_dispatch(raw: str) -> str:
    d = raw.replace("-", "")
    return f"{d[:1]}-{d[1:2]}-{d[2:6]}-{d[6:]}"


def _find(pages: PageText, pattern: re.Pattern[str], normalize=None) -> RuleCandidate | None:
    """쪽 순서대로 보아 처음 찾은 쪽의 첫 값을 돌려준다. 같은 쪽에 다른 값이 또 있으면 ambiguous."""
    for page in pages.pages:
        found = [m.group(1) for m in pattern.finditer(page.text)]
        if not found:
            continue
        keyed = [normalize(f) if normalize else None for f in found]
        # 값(정규화한 것, 날짜는 글자)이 서로 다른 게 둘 이상이면 애매
        distinct = set(keyed) if normalize else set(found)
        return RuleCandidate(
            value=keyed[0] if normalize else None,
            raw_text=found[0],
            page=page.page,
            ambiguous=len(distinct) > 1,
        )
    return None


def extract_by_rules(pages: PageText) -> RuleFields:
    """출원번호·발송번호·통지일·제출기일을 뽑는다. 못 찾은 칸은 None."""
    return RuleFields(
        application_number=_find(pages, _APP_NO, _hyphenate_app),
        dispatch_number=_find(pages, _DISPATCH_NO, _hyphenate_dispatch),
        notice_date=_find(pages, _NOTICE_DATE),
        response_due=_find(pages, _RESPONSE_DUE),
    )


# ---- 조문 ----
_ARTICLE_TOKEN = re.compile(r"제\s*([^\s조항호제]*)\s*(조|항|호)")
_ARTICLE_ORDER = ["조", "항", "호"]


def normalize_article(text: str) -> str | None:
    """`특허법 제29조제2항` -> `29-2`, `제42조제4항제2호` -> `42-4-2`. 깨졌으면 None."""
    tokens = _ARTICLE_TOKEN.findall(text)
    # 조가 맨 앞이고, 조 -> 항 -> 호 순서로 한 번씩만, 번호는 숫자여야 한다
    units = [u for _, u in tokens]
    if not tokens or units != _ARTICLE_ORDER[: len(units)]:
        return None
    if any(not num.isdigit() for num, _ in tokens):
        return None
    return "-".join(num for num, _ in tokens)


# ---- 청구항 범위 ----
_MAX_CLAIM = 1000  # 이보다 큰 번호는 글자 오류로 본다


def expand_claims(text: str) -> list[int] | None:
    """`제1항 내지 제4항, 제6항` -> [1,2,3,4,6]. 해석 못 하는 글자가 있으면 None."""
    # 군더더기(청구항·제·항)를 지우고 `내지`·`~`는 `-`로 바꿔 `1-4,6` 꼴로 만든다
    s = text.replace("내지", "-").replace("~", "-")
    s = s.replace("및", ",").replace("와", ",").replace("과", ",")  # 이음말은 쉼표로
    s = re.sub(r"청구항|[제항]|\s+", "", s)
    if not s:
        return None
    numbers: set[int] = set()
    for part in s.split(","):
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            return None  # 숫자가 아닌 것이 섞임: 지어내지 않는다
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        if start < 1 or end < start or end > _MAX_CLAIM:
            return None
        numbers.update(range(start, end + 1))
    return sorted(numbers)


# ---- 통지 종류 ----
# 글자 사이에 공백·줄바꿈이 끼어도 찾는다
_FINAL_MARK = re.compile(r"최\s*후\s*거\s*절\s*이\s*유\s*통\s*지")
_INITIAL_CHECKED = "최후 표시 없음, 1쪽 머리말·거절이유 표 아래·[첨 부] 앞을 봄"


def notice_kind_of(pages: PageText) -> ExtractedValue[NoticeKind]:
    """통지 종류. 최후 표시 -> final(원문·쪽) / 머리말을 읽었는데 표시 없음 -> initial /
    머리말을 못 읽음 -> unknown + unverified(not_extracted)."""
    first = next((p for p in pages.pages if p.page == 1), None)
    header = "\n".join(first.text.splitlines()[:HEADER_LINES]) if first else ""
    # [가정] 머리말을 읽었다 = 첫 15줄에 통지서 제목 글자("통지")가 있다
    if "통지" not in header:
        return ExtractedValue[NoticeKind](
            value=NoticeKind.UNKNOWN,
            status=Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED),
        )
    m = _FINAL_MARK.search(header)
    if m:
        return ExtractedValue[NoticeKind](
            value=NoticeKind.FINAL,
            raw_text=m.group(0),
            page=1,
            status=Status(value=StatusValue.CONFIRMED, checked="1쪽 머리말에서 최후 표시를 찾음"),
        )
    return ExtractedValue[NoticeKind](
        value=NoticeKind.INITIAL,
        status=Status(value=StatusValue.CONFIRMED, checked=_INITIAL_CHECKED),
    )
