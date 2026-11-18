"""통지서 글자에서 규칙(정규식)으로 뽑는 것: 번호·날짜 글자·조문·청구항 범위·통지 종류.

모양의 기준은 docs/features/F1/design.md 2절 ③과 필드 출처 표.
못 찾거나 애매하면 None을 돌려준다 (값을 지어내지 않는다).
"""

import re
from dataclasses import dataclass

from patent_ai.core.f1_oa_reader.verify import Found
from patent_ai.core.schemas.common import ExtractedValue, Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.document import PageText
from patent_ai.core.schemas.oa_result import NoticeKind

# [가정] 1쪽 머리말 = 1쪽 글자의 첫 15줄. 표본 OA로 확인 (#22).
HEADER_LINES = 15


def loose_pattern(text: str) -> re.Pattern[str]:
    """글자 사이에 공백·줄바꿈이 끼어도 찾는 정규식 (text 안의 공백은 무시)."""
    return re.compile(r"\s*".join(re.escape(ch) for ch in text if not ch.isspace()))


@dataclass(frozen=True)
class RuleFields:
    application_number: Found | None = None
    dispatch_number: Found | None = None
    notice_date: Found | None = None
    response_due: Found | None = None


# [가정] 형식: 출원번호 10-YYYY-NNNNNNN, 발송번호 9-5-YYYY-NNNNNNNNN (하이픈은 있어도 없어도),
# 날짜 YYYY.MM.DD. 이름표(출원번호·발송일자 등) 바로 뒤의 값만 뽑는다.
# 인용문헌의 번호를 출원번호로 잘못 뽑지 않으려는 것이다.
_GAP = r"[^\d\n]{0,8}"  # 이름표와 값 사이의 짧은 글자(공백·콜론 등)
_APP_BODY = r"10-?\d{4}-?\d{7}(?!\d)"  # 출원번호 모양 (이름표 찾기와 글자 속 찾기가 같이 씀)
_DISPATCH_BODY = r"9-?5-?\d{4}-?\d{9}(?!\d)"
_APP_NO = re.compile(r"출원번호" + _GAP + "(" + _APP_BODY + ")")
_DISPATCH_NO = re.compile(r"발송번호" + _GAP + "(" + _DISPATCH_BODY + ")")
_DATE = r"(\d{4}\.\s?\d{1,2}\.\s?\d{1,2}\.)"
_NOTICE_DATE = re.compile(r"(?:발송일자|발송일|통지일)" + _GAP + _DATE)
_RESPONSE_DUE = re.compile(r"(?:제출기일|제출기한)" + _GAP + _DATE)


def _digits(raw: str) -> str:
    """번호 값은 하이픈 없는 숫자만 (정답 형식 1020990000001). 글자(raw_text)는 원문 그대로."""
    return raw.replace("-", "")


def normalize_application_number(text: str) -> str | None:
    """글자 속 출원번호(`10-YYYY-NNNNNNN`, 하이픈 있어도 없어도)를 숫자만으로. 없으면 None."""
    m = re.search(_APP_BODY, text)
    return _digits(m.group(0)) if m else None


def normalize_dispatch_number(text: str) -> str | None:
    """글자 속 발송번호(`9-5-YYYY-NNNNNNNNN`)를 숫자만으로. 없으면 None."""
    m = re.search(_DISPATCH_BODY, text)
    return _digits(m.group(0)) if m else None


def _find(pages: PageText, pattern: re.Pattern[str], normalize=None) -> Found | None:
    """쪽 순서대로 보아 처음 찾은 쪽의 첫 값을 돌려준다. 같은 쪽에 다른 값이 또 있으면 ambiguous."""
    for page in pages.pages:
        found = [m.group(1) for m in pattern.finditer(page.text)]
        if not found:
            continue
        keyed = [normalize(f) if normalize else None for f in found]
        # 값(정규화한 것, 날짜는 글자)이 서로 다른 게 둘 이상이면 애매
        distinct = set(keyed) if normalize else set(found)
        return Found(
            value=keyed[0] if normalize else None,
            raw_text=found[0],
            page=page.page,
            ambiguous=len(distinct) > 1,
        )
    return None


def extract_by_rules(pages: PageText) -> RuleFields:
    """출원번호·발송번호·통지일·제출기일을 뽑는다. 못 찾은 칸은 None."""
    return RuleFields(
        application_number=_find(pages, _APP_NO, _digits),
        dispatch_number=_find(pages, _DISPATCH_NO, _digits),
        notice_date=_find(pages, _NOTICE_DATE),
        response_due=_find(pages, _RESPONSE_DUE),
    )


# ---- 조문 ----
_ARTICLE_TOKEN = re.compile(r"제\s*([^\s조항호제]*)\s*(조|항|호)")


def normalize_article(text: str) -> str | None:
    """`특허법 제29조제2항` -> `29-2`, `제42조제4항제2호` -> `42-4-2`.

    호가 여럿이면 `|`로 잇는다: `제29조제1항제1호 및 제2호` -> `29-1-1|29-1-2`. 깨졌으면 None.
    """
    if re.search(r"조\s*의\s*\d", text):
        return None  # `제29조의2`(확대된 선출원 등)는 `29-2`(진보성)와 섞이지 않게 거부
    tokens = _ARTICLE_TOKEN.findall(text)
    if not tokens or any(not num.isdigit() for num, _ in tokens):
        return None
    units = [u for _, u in tokens]
    # 조가 맨 앞, 그 뒤 항(있으면 한 번), 그 뒤 호(여럿 가능). 호는 항 다음에만 온다
    if units[0] != "조" or (len(units) > 1 and units[1] != "항"):
        return None
    if any(u != "호" for u in units[2:]):
        return None
    base = "-".join(num for num, _ in tokens[:2])
    hos = [num for num, _ in tokens[2:]]
    return "|".join(f"{base}-{h}" for h in hos) if hos else base


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
_FINAL_MARK = loose_pattern("최후거절이유통지")
_TITLE = loose_pattern("의견제출통지서")
_INITIAL_CHECKED = "최후 표시 없음, 모든 쪽 글자를 봄"


# [가정] 본문 문장 속 언급("...통지에 해당하지 않음", "앞선 ...통지에 대한 보정")은
# 표시가 아니다. 규칙: 바로 뒤에 한글 조사·서술이 붙거나(단 제목 끝 "서"는 허용),
# 바로 앞 6글자에 앞선·이전·종전이 있으면 뺀다. 표본 OA로 확인 (#22).
_PAST_WORDS = ("앞선", "이전", "종전")


def _is_mark(text: str, m: re.Match[str]) -> bool:
    before = text[max(0, m.start() - 6) : m.start()]
    if any(w in before for w in _PAST_WORDS):
        return False
    after = text[m.end() : m.end() + 1]
    # 뒤가 한글이면 문장의 일부 ("에", "를", "의" ...). 홀로 있거나 괄호·줄바꿈·"서"면 표시
    return not ("가" <= after <= "힣" and after != "서")


def notice_kind_of(pages: PageText) -> ExtractedValue[NoticeKind]:
    """통지 종류. 최후 표시가 어느 쪽에든 있으면 final(원문·쪽) /
    머리말에 `의견제출통지서` 제목이 있고 최후 표시는 없으면 initial /
    머리말(제목)을 못 읽으면 unknown + unverified(not_extracted)."""
    first = next((p for p in pages.pages if p.page == 1), None)
    header = "\n".join(first.text.splitlines()[:HEADER_LINES]) if first else ""
    # 1) 모든 쪽에서 최후 표시를 찾는다 (쪽 순서대로 처음 것)
    for page in pages.pages:
        m = next((m for m in _FINAL_MARK.finditer(page.text) if _is_mark(page.text, m)), None)
        if m:
            return ExtractedValue[NoticeKind](
                value=NoticeKind.FINAL,
                raw_text=m.group(0),
                page=page.page,
                status=Status(value=StatusValue.CONFIRMED, checked="최후 표시를 찾음"),
            )
    # 2) 제목을 읽었는데 표시가 없다 -> initial (쪽 없음)
    if _TITLE.search(header):
        return ExtractedValue[NoticeKind](
            value=NoticeKind.INITIAL,
            status=Status(value=StatusValue.CONFIRMED, checked=_INITIAL_CHECKED),
        )
    # 3) 머리말을 못 읽음
    return ExtractedValue[NoticeKind](
        value=NoticeKind.UNKNOWN,
        status=Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED),
    )


# ---- 인용 위치(식별번호 칸) ----
# 정답 형식(f1-oa-gold.md 2.4): 문단 `[0016]`, 범위 `[0080]-[0081]`, 도면 `도 4c`,
# 인용문헌 청구항 `청구항 9`, `요약`, 미국 칼럼·줄 `3:5-10`
_LOC_NOISE = re.compile(
    r"등\s*참조|참조|식별번호|단락\s*번호|단락|문단|paragraphs?|para\.?", re.IGNORECASE
)
_LOC_TOKEN = re.compile(
    r"""
    (?P<range>\[\s*(?P<ra>\d+)\s*\]\s*(?:-|~|내지)\s*\[\s*(?P<rb>\d+)\s*\])
    |\[(?P<group>[\d\s,~\-]+)\]
    |(?<![가-힣])도면?\s*(?P<fig>\d+[A-Za-z]?(?:\s*(?:,|및)\s*\d+[A-Za-z]?(?![\d:A-Za-z]|\s*:))*)
    |청구항\s*제?\s*(?P<claim>\d+)\s*항?
    |(?P<abstract>요약)
    |(?:col\.?\s*)?(?P<col>\d+)\s*(?::|,\s*ll?\.?)\s*(?P<l1>\d+)(?:\s*[-~]\s*(?P<l2>\d+))?
    """,
    re.VERBOSE,
)
_LOC_SEPARATOR = re.compile(r"[\s,;/]|및")
_MAX_PARAGRAPH = 9999  # 문단 번호는 4자리까지


def _paragraph(n: str) -> str | None:
    return f"[{int(n):04d}]" if int(n) <= _MAX_PARAGRAPH else None


def _paragraph_range(a: str, b: str) -> str | None:
    first, last = _paragraph(a), _paragraph(b)
    if first is None or last is None or int(a) > int(b):
        return None
    return f"{first}-{last}"


def _paragraph_group(body: str) -> list[str] | None:
    """`[16, 38, 78]`, `[0080-0081]` 속 내용을 `[0016]`, `[0038]`… 로."""
    out: list[str] = []
    for part in body.split(","):
        m = re.fullmatch(r"\s*(\d+)(?:\s*[-~]\s*(\d+))?\s*", part)
        if not m:
            return None
        one = _paragraph_range(m.group(1), m.group(2)) if m.group(2) else _paragraph(m.group(1))
        if one is None:
            return None
        out.append(one)
    return out


def parse_cited_locations(raw: str) -> list[str] | None:
    """식별번호 칸 글자를 정답 꼴 목록으로. 못 읽는 조각이 있으면 None (지어내지 않는다)."""
    text = _LOC_NOISE.sub(" ", raw)
    out: list[str] = []
    pos = 0
    for m in _LOC_TOKEN.finditer(text):
        # 토큰 사이에 구분자 말고 남은 글자가 있으면 못 읽는 조각
        if _LOC_SEPARATOR.sub("", text[pos : m.start()]):
            return None
        pos = m.end()
        if m.group("range"):
            one = _paragraph_range(m.group("ra"), m.group("rb"))
            found = [one] if one else None
        elif m.group("group") is not None:
            found = _paragraph_group(m.group("group"))
        elif m.group("fig"):
            found = [f"도 {n}" for n in re.findall(r"\d+[A-Za-z]?", m.group("fig"))]
        elif m.group("claim"):
            found = [f"청구항 {int(m.group('claim'))}"]
        elif m.group("abstract"):
            found = ["요약"]
        else:
            end = f"-{m.group('l2')}" if m.group("l2") else ""
            found = [f"{m.group('col')}:{m.group('l1')}{end}"]
        if found is None:
            return None
        out += found
    if _LOC_SEPARATOR.sub("", text[pos:]):
        return None
    return out or None
