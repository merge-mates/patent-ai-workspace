"""F1 비교 규칙 (정답 형식 2.4·3절, #110, #20 결정). 모두 순수 함수."""

import re

_WS = re.compile(r"\s+")
# 따옴표 종류 (명확성 표현 비교에서 지운다)
_QUOTES = re.compile(r"[\"'“”‘’「」『』]")
# 특허 키: 나라 2글자 + 번호 + (종류 코드). 종류 코드는 보지 않는다 (#110)
_PATENT_KEY = re.compile(r"([A-Z]{2})(\d+)(?:[A-Z]\d?)?")


def norm_text(s: str | None) -> str | None:
    """공백·줄바꿈만 지운다 (requirements 9번 '확인하지 않은 원문 위치'와 같은 규칙)."""
    return None if s is None else _WS.sub("", s)


def text_eq(a: str | None, b: str | None) -> bool:
    return norm_text(a) == norm_text(b)


def cite_key(key: str | None) -> str | None:
    """인용 키를 나라+번호로 줄인다. 논문(NPL) 등 특허 꼴이 아니면 공백만 지운다."""
    if key is None:
        return None
    m = _PATENT_KEY.fullmatch(key.strip())
    if m:
        return m.group(1) + m.group(2)
    return norm_text(key)


def _clarity_norm(s: str) -> str:
    return _QUOTES.sub("", _WS.sub("", s))


def clarity_match(gold_terms: list[str], pred_terms: list[str]) -> bool:
    """명확성 표현: 공백·따옴표를 지우고 한쪽이 다른 쪽에 들어 있으면 맞음 (2.4).

    정답이 빈 목록(따옴표 없는 명확성, 3절 11번)이면 줄이 있는 것만으로 맞음.
    """
    if not gold_terms:
        return True
    for g in map(_clarity_norm, gold_terms):
        for p in map(_clarity_norm, pred_terms):
            if g and p and (g in p or p in g):
                return True
    return False


def same_as_match(gold: list[str], pred: list[str]) -> bool:
    """같은 취지: 하나라도 겹치면 맞음 (3절 2번, 짝을 안 지은 묶음)."""
    return bool(set(gold) & set(pred))


def page_in(gold_page: int, gold_end: int | None, pred_page: int | None) -> bool:
    """줄 쪽: 예측 쪽이 정답 시작~끝 쪽 안이면 맞음 (#110)."""
    if pred_page is None:
        return False
    return gold_page <= pred_page <= (gold_end or gold_page)


NO_LOCATION_PREFIX = "위치 없음"


def location_pairs(locations: dict[str, list[str]]) -> set[tuple[str, str]]:
    """(라벨, 위치) 쌍. `위치 없음 (…)`은 위치 채점에서 뺀다 (3절 4번)."""
    return {
        (label, loc)
        for label, locs in locations.items()
        for loc in locs
        if not loc.startswith(NO_LOCATION_PREFIX)
    }
