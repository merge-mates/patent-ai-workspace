"""맞음 판정: 조각이 정답 항목을 맞혔나 (design 7-1 인터페이스, 7-4 규칙).

정답 줄 타입(GoldItem, GoldRow)은 gold.py가 만든다. 여기서는 필요한 칸만 Protocol로 받는다.
정렬 키 인코딩: 문단 = 번호, 칼럼:줄 = 칼럼 x 10000 + 줄, 쪽 = 쪽 번호.
"""

from collections.abc import Callable
from datetime import date
from typing import Protocol

from patent_ai.retrieval.schemas import Chunk, Corpus


class GoldItem(Protocol):
    kind: str
    start: int | None
    end: int | None
    figures: list[int]
    claims: list[int]  # claim 항목용 청구항 번호들
    label: str


class GoldEdition(Protocol):
    status: str
    effective_from: date | None


class GoldRow(Protocol):
    corpus: str
    doc_ids: list[str] | None
    gold_edition: GoldEdition | None


class Matcher(Protocol):
    def matches(self, chunk: Chunk, item: GoldItem, row: GoldRow) -> bool: ...


class UnknownLocationRuleError(ValueError):
    """등록되지 않은 법령 위치 규칙 이름."""


def _overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start <= b_end and b_start <= a_end


def _same_kind_and_overlap_or_label(chunk: Chunk, item: GoldItem) -> bool:
    """같은 종류이고 정렬 키가 겹치면 맞음. 키가 null이면 label 글자가 같을 때만 맞음."""
    loc = chunk.location
    if loc.kind != item.kind:
        return False
    if None in (loc.start, loc.end, item.start, item.end):
        return loc.label == item.label
    return _overlap(loc.start, loc.end, item.start, item.end)


# 법령 위치 규칙 등록표: 이름 -> (조각, 항목) -> bool. #66이 새 이름만 더한다
LAW_LOCATION_RULES: dict[str, Callable[[Chunk, GoldItem], bool]] = {}
DEFAULT_LAW_LOCATION_RULE = "overlap_or_label"


def register_law_location_rule(name: str):
    def deco(fn: Callable[[Chunk, GoldItem], bool]):
        # 같은 이름에 다른 함수가 오면 막는다 (기본 규칙 덮어쓰기 포함). 같은 함수 재등록은 허용
        if name in LAW_LOCATION_RULES and LAW_LOCATION_RULES[name] is not fn:
            raise ValueError(f"위치 규칙 이름 {name!r}이 이미 다른 함수로 등록돼 있다")
        LAW_LOCATION_RULES[name] = fn
        return fn

    return deco


register_law_location_rule(DEFAULT_LAW_LOCATION_RULE)(_same_kind_and_overlap_or_label)


class CiteMatcher:
    """인용문헌: 공보가 같고 항목 종류에 맞는 위치여야 맞음."""

    def matches(self, chunk: Chunk, item: GoldItem, row: GoldRow) -> bool:
        # 1. 정답 줄의 공보 안이어야 한다 (다른 공보는 틀림)
        if row.doc_ids is not None and chunk.doc_id not in row.doc_ids:
            return False
        loc = chunk.location
        if item.kind == "figure":
            # 도면 번호를 담은 조각이면 본문이어도 맞음
            return bool(set(loc.figures) & set(item.figures))
        if item.kind == "claim":
            return bool(set(loc.claims) & set(item.claims))
        if item.kind == "abstract":
            return chunk.chunk_kind == "abstract"
        # paragraph / column_line / page: 종류가 같고 겹침, 키가 null이면 label
        return _same_kind_and_overlap_or_label(chunk, item)


class LawMatcher:
    """법령: 판본(시행 시작일)이 정답과 같고 위치 규칙을 통과해야 맞음."""

    def __init__(self, location_rule: str = DEFAULT_LAW_LOCATION_RULE):
        if location_rule not in LAW_LOCATION_RULES:
            names = ", ".join(sorted(LAW_LOCATION_RULES))
            raise UnknownLocationRuleError(
                f"없는 위치 규칙 {location_rule!r}. 쓸 수 있는 이름: {names}"
            )
        self.location_rule = LAW_LOCATION_RULES[location_rule]

    def matches(self, chunk: Chunk, item: GoldItem, row: GoldRow) -> bool:
        gold = row.gold_edition
        # 판본을 모르는 쪽(조각 또는 정답)이 있으면 맞다고 하지 않는다
        if gold is None or gold.status != "confirmed" or gold.effective_from is None:
            return False
        if chunk.edition.status != "confirmed":
            return False
        if chunk.edition.effective_from != gold.effective_from:
            return False
        return self.location_rule(chunk, item)


# law 칸은 기본 위치 규칙이다. 채점기는 설정의 law_location_rule로 LawMatcher를 새로 만든다
# (score._matcher_for). 설정 규칙을 쓰려면 MATCHERS["law"] 대신 그쪽을 쓴다.
MATCHERS: dict[Corpus, Matcher] = {"cite": CiteMatcher(), "law": LawMatcher()}
