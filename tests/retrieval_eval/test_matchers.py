"""맞음 판정 (design 7-4). 정답 줄·항목은 가짜 dataclass로 만든다."""

from dataclasses import dataclass, field
from datetime import date

import pytest

from eval.retrieval import matchers as matchers_mod
from eval.retrieval.matchers import (
    MATCHERS,
    CiteMatcher,
    LawMatcher,
    UnknownLocationRuleError,
    register_law_location_rule,
)
from patent_ai.retrieval.schemas import Chunk, Edition, Location


@pytest.fixture(autouse=True)
def _등록표_되돌리기():
    """테스트가 전역 위치 규칙 등록표에 남긴 이름을 테스트 끝에 지운다."""
    saved = dict(matchers_mod.LAW_LOCATION_RULES)
    yield
    matchers_mod.LAW_LOCATION_RULES.clear()
    matchers_mod.LAW_LOCATION_RULES.update(saved)


@dataclass
class GoldEdition:
    status: str
    effective_from: date | None = None


@dataclass
class Item:
    kind: str
    start: int | None = None
    end: int | None = None
    figures: list[int] = field(default_factory=list)
    claims: list[int] = field(default_factory=list)
    label: str = ""
    gold_edition: GoldEdition | None = None  # 법령 항목마다 정답 판본


@dataclass
class Row:
    corpus: str
    doc_ids: list[str] | None


def chunk(
    doc_id="KR1A",
    chunk_kind="body",
    kind="paragraph",
    start=None,
    end=None,
    label="",
    figures=(),
    claims=(),
    edition=None,
):
    return Chunk(
        chunk_id=f"{doc_id}:{label}",
        index_version="v1",
        doc_id=doc_id,
        chunk_kind=chunk_kind,
        location=Location(
            kind=kind,
            start=start,
            end=end,
            label=label,
            figures=list(figures),
            claims=list(claims),
        ),
        edition=edition or Edition(status="not_applicable"),
        text="본문",
    )


CITE_ROW = Row("cite", ["KR1A"])
CITE = CiteMatcher()


def test_matchers_등록표에_두_말뭉치가_있다():
    assert isinstance(MATCHERS["cite"], CiteMatcher)
    assert isinstance(MATCHERS["law"], LawMatcher)


def test_cite_문단_범위_안의_문단은_맞다():
    item = Item("paragraph", 22, 25, label="[0022-0025]")
    assert CITE.matches(chunk(start=23, end=23, label="[0023]"), item, CITE_ROW)


def test_cite_같은_공보_다른_문단은_틀리다():
    item = Item("paragraph", 22, 25, label="[0022-0025]")
    assert not CITE.matches(chunk(start=30, end=30, label="[0030]"), item, CITE_ROW)


def test_cite_다른_공보는_틀리다():
    item = Item("paragraph", 22, 25)
    other = chunk(doc_id="KR2A", start=23, end=23, label="[0023]")
    assert not CITE.matches(other, item, CITE_ROW)


def test_cite_칼럼줄이_겹치면_맞다():
    item = Item("column_line", 30050, 40005, label="3:50-4:5")
    c = chunk(kind="column_line", start=30060, end=30070, label="3:60-3:70")
    assert CITE.matches(c, item, CITE_ROW)


def test_cite_칼럼줄이_안_겹치면_틀리다():
    item = Item("column_line", 30050, 40005)
    c = chunk(kind="column_line", start=40006, end=40010, label="4:6-4:10")
    assert not CITE.matches(c, item, CITE_ROW)


def test_cite_종류가_다르면_숫자가_겹쳐도_틀리다():
    item = Item("column_line", 22, 25)
    assert not CITE.matches(chunk(kind="paragraph", start=23, end=23), item, CITE_ROW)


def test_cite_도면을_담은_본문_조각도_맞다():
    item = Item("figure", figures=[3], label="도 3")
    assert CITE.matches(chunk(figures=[2, 3], label="[0040]"), item, CITE_ROW)
    assert CITE.matches(chunk(chunk_kind="figure_desc", kind="figure", figures=[3]), item, CITE_ROW)


def test_cite_다른_도면은_틀리다():
    item = Item("figure", figures=[3])
    assert not CITE.matches(chunk(figures=[4]), item, CITE_ROW)


def test_cite_청구항_항목은_청구항_번호가_겹치면_맞다():
    item = Item("claim", claims=[1])
    assert CITE.matches(chunk(chunk_kind="claim", kind="claim", claims=[1, 2]), item, CITE_ROW)
    assert not CITE.matches(chunk(chunk_kind="claim", kind="claim", claims=[3]), item, CITE_ROW)


def test_cite_요약_조각은_요약_항목에_맞다():
    item = Item("abstract", label="요약")
    assert CITE.matches(chunk(chunk_kind="abstract", kind="abstract"), item, CITE_ROW)
    assert not CITE.matches(chunk(), item, CITE_ROW)


def test_cite_정렬키가_null이면_label이_같을_때만_맞다():
    item = Item("paragraph", None, None, label="[0023]")
    assert CITE.matches(chunk(label="[0023]"), item, CITE_ROW)
    assert not CITE.matches(chunk(label="[0024]"), item, CITE_ROW)


def test_cite_조각만_정렬키가_null이어도_label로_본다():
    item = Item("paragraph", 23, 23, label="[0023]")
    assert CITE.matches(chunk(label="[0023]"), item, CITE_ROW)
    assert not CITE.matches(chunk(label="[0024]"), item, CITE_ROW)


def law_chunk(start=3203, end=3203, label="3203쪽", status="confirmed", eff=date(2020, 1, 1)):
    return chunk(
        doc_id="law",
        chunk_kind="article",
        kind="page",
        start=start,
        end=end,
        label=label,
        edition=Edition(status=status, effective_from=eff),
    )


LAW_ROW = Row("law", None)
LAW_ITEM = Item(
    "page", 3203, 3204, label="3203~3204쪽", gold_edition=GoldEdition("confirmed", date(2020, 1, 1))
)


def test_law_판본_같고_위치_겹치면_맞다():
    assert LawMatcher().matches(law_chunk(), LAW_ITEM, LAW_ROW)


def test_law_판본이_다르면_틀리다():
    other = law_chunk(eff=date(2019, 1, 1))
    assert not LawMatcher().matches(other, LAW_ITEM, LAW_ROW)


def test_law_조각_판본을_모르면_틀리다():
    assert not LawMatcher().matches(law_chunk(status="unverified", eff=None), LAW_ITEM, LAW_ROW)


def test_law_정답_판본을_모르면_틀리다():
    item = Item("page", 3203, 3204, label="3203~3204쪽", gold_edition=GoldEdition("unverified"))
    assert not LawMatcher().matches(law_chunk(), item, LAW_ROW)


def test_law_판본은_항목마다_본다():
    # 한 줄의 두 항목이 다른 판본이면, 조각 판본과 같은 항목만 맞다
    new = Item(
        "page",
        3203,
        3204,
        label="3203~3204쪽",
        gold_edition=GoldEdition("confirmed", date(2020, 1, 1)),
    )
    old = Item(
        "page",
        3203,
        3204,
        label="3203~3204쪽",
        gold_edition=GoldEdition("confirmed", date(2019, 1, 1)),
    )
    assert LawMatcher().matches(law_chunk(), new, LAW_ROW)
    assert not LawMatcher().matches(law_chunk(), old, LAW_ROW)


def test_law_위치가_안_겹치면_틀리다():
    assert not LawMatcher().matches(law_chunk(start=3300, end=3300), LAW_ITEM, LAW_ROW)


def test_law_정렬키가_null이면_label이_같을_때만_맞다():
    item = Item(
        "page", None, None, label="3203쪽", gold_edition=GoldEdition("confirmed", date(2020, 1, 1))
    )
    assert LawMatcher().matches(law_chunk(start=None, end=None, label="3203쪽"), item, LAW_ROW)
    assert not LawMatcher().matches(law_chunk(start=None, end=None, label="3300쪽"), item, LAW_ROW)


def test_law_위치_규칙을_등록해_이름으로_고른다():
    @register_law_location_rule("test_always")
    def always(chunk, item):
        return True

    # 위치가 안 겹쳐도 규칙이 참이면 맞다. 판본 검사는 그대로 한다
    far = law_chunk(start=9000, end=9000)
    assert LawMatcher("test_always").matches(far, LAW_ITEM, LAW_ROW)
    wrong_edition = law_chunk(eff=date(2019, 1, 1))
    assert not LawMatcher("test_always").matches(wrong_edition, LAW_ITEM, LAW_ROW)


def test_law_없는_위치_규칙_이름은_오류():
    with pytest.raises(UnknownLocationRuleError, match="overlap_or_label"):
        LawMatcher("no_such_rule")


def test_law_같은_이름에_다른_함수를_등록하면_오류():
    @register_law_location_rule("dup_rule")
    def first(chunk, item):
        return True

    with pytest.raises(ValueError, match="dup_rule"):

        @register_law_location_rule("dup_rule")
        def second(chunk, item):
            return False

    # 기본 규칙 덮어쓰기도 막힌다
    with pytest.raises(ValueError, match="overlap_or_label"):

        @register_law_location_rule("overlap_or_label")
        def hijack(chunk, item):
            return True
