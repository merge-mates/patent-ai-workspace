"""지원 조문 표와 인용문헌 나라 판정 (design.md 2절 ⑥). 표는 실험 값이 아니라 코드 상수다."""

import re

from patent_ai.core.schemas.common import ExtractedValue, Status, StatusValue, UnverifiedReason

# 신규성(29-1)·진보성(29-2)·명확성(42-4-2)만 지원. 그 밖은 직접 검토 필요.
SUPPORTED_ARTICLES = {"29-1", "29-2", "42-4-2"}

# 위에서부터 먼저 맞는 나라. 영문 코드는 앞뒤에 영문자가 없을 때만 (다른 단어 속 글자 방지)
_COUNTRY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "KR",
        re.compile(r"공개특허공보\s*제\s*10-\d{4}-\d{7}\s*호|등록특허공보\s*제\s*10-\d{7}\s*호"),
    ),
    ("KR", re.compile(r"(?<![A-Za-z])KR(?![A-Za-z])")),
    ("US", re.compile(r"(?<![A-Za-z])US(?![A-Za-z])|미국")),
    ("JP", re.compile(r"(?<![A-Za-z])JP(?![A-Za-z])|일본")),
    ("CN", re.compile(r"(?<![A-Za-z])CN(?![A-Za-z])|중국")),
    ("EP", re.compile(r"(?<![A-Za-z])EP(?![A-Za-z])")),
    ("WO", re.compile(r"(?<![A-Za-z])WO(?![A-Za-z])")),
]


def is_supported(article: str) -> bool:
    """정규화한 조문("29-2")이 지원 표에 있나."""
    return article in SUPPORTED_ARTICLES


def country_of(text: str, page: int | None = None) -> ExtractedValue[str]:
    """인용문헌 표기 글자에서 나라를 정한다. 맞는 것이 없으면 value null + ambiguous."""
    has_text = bool(text.strip())
    # 글자가 비면 쪽도 남기지 않는다 (쪽이 있으면 글자도 있어야 함)
    raw_text = text if has_text else None
    page = page if has_text else None
    for country, pattern in _COUNTRY_PATTERNS:
        if has_text and pattern.search(text):
            return ExtractedValue(
                value=country,
                raw_text=raw_text,
                page=page,
                status=Status(value=StatusValue.CONFIRMED, checked="인용 표기에서 나라 판정"),
            )
    return ExtractedValue(
        value=None,
        raw_text=raw_text,
        page=page,
        status=Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.AMBIGUOUS),
    )
