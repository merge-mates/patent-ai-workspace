"""판단 단위 만들기 테스트 (코드 도구). 기대값은 F3 뼈대 설계 2절과 JudgmentUnit 스키마 규칙."""

import logging

from patent_ai.core.f3_claim_compare.units import build_units
from patent_ai.core.schemas.common import Flag, StatusValue, UnverifiedReason
from patent_ai.core.schemas.judgment_unit import UnitKind
from patent_ai.core.schemas.oa_result import RejectionKind
from tests.core.f3.fakes import oa, rejection, split

# 1·4는 독립항, 2는 1을, 3은 2를, 5는 1과 4를 인용한다
SPLITS = {
    1: split(1, ["물통"]),
    2: split(2, ["투명한 재질"], [1]),
    3: split(3, ["눈금"], [2]),
    4: split(4, ["받침"]),
    5: split(5, ["손잡이"], [1, 4]),
}


def _units(rejections, splits=None):
    return build_units(oa(rejections), SPLITS if splits is None else splits)


def test_진보성은_독립항_묶음이고_여러_항을_인용한_종속항은_묶음마다_들어간다():
    units, held = _units([rejection(1, "29-2", [1, 2, 3, 4, 5])])
    assert held == []
    assert [u.unit_id for u in units] == ["oa_1:29-2:c1", "oa_1:29-2:c4"]
    first, second = units
    assert (first.representative_claim, first.claims) == (1, [1, 2, 3, 5])
    assert (second.representative_claim, second.claims) == (4, [4, 5])
    assert first.unit_kind == second.unit_kind == UnitKind.INDEPENDENT_GROUP
    assert first.rejection_kind == RejectionKind.INVENTIVE_STEP and first.rejection == 1
    assert [u.order for u in units] == [1, 2]
    assert first.status.value == StatusValue.CONFIRMED
    assert first.read_with == []


def test_신규성도_독립항_묶음이고_조문이_unit_id에_들어간다():
    units, _ = _units([rejection(1, "29-1-1|29-1-2", [1, 2])])
    (unit,) = units
    assert unit.unit_id == "oa_1:29-1-1|29-1-2:c1"
    assert unit.rejection_kind == RejectionKind.NOVELTY and unit.claims == [1, 2]


def test_명확성은_청구항_하나이고_인용하는_앞_청구항을_함께_읽는다():
    units, _ = _units([rejection(1, "42-4-2", [1, 3])])
    assert [u.unit_id for u in units] == ["oa_1:42-4-2:c1", "oa_1:42-4-2:c3"]
    independent, dependent = units
    assert independent.unit_kind == UnitKind.SINGLE_CLAIM
    assert (independent.claims, independent.read_with) == ([1], [])
    assert (dependent.claims, dependent.read_with) == ([3], [1, 2])  # 3 → 2 → 1


def test_같은_입력을_두_번_묶으면_결과가_같다():
    rejections = [rejection(1, "29-2", [1, 2, 3, 4, 5]), rejection(2, "42-4-2", [3])]
    assert _units(rejections) == _units(rejections)


def test_거절이유가_여럿이면_거절이유_순서대로_순서를_매긴다():
    units, _ = _units([rejection(1, "29-2", [1, 2]), rejection(2, "42-4-2", [2, 1])])
    assert [(u.unit_id, u.order) for u in units] == [
        ("oa_1:29-2:c1", 1),
        ("oa_1:42-4-2:c1", 2),  # 독립항 먼저
        ("oa_1:42-4-2:c2", 3),
    ]


def test_독립항이_대상이_아니면_대상_청구항만으로_묶는다(caplog):
    # 11/21 재아가 결정을 바꿈: 경고·표시 대신, 대비 단계가 부모(청구항 1) 구성요소를
    # 종속항 대비에 같이 넣는다 (test_f3_parent_elements.py)
    with caplog.at_level(logging.WARNING):
        units, _ = _units([rejection(1, "29-2", [2, 3])])
    (unit,) = units
    assert (unit.unit_id, unit.claims) == ("oa_1:29-2:c2", [2, 3])
    assert unit.status.value == StatusValue.CONFIRMED and unit.flags == []
    assert not any("독립항" in r.getMessage() for r in caplog.records)


def test_인용_관계를_확인하지_못한_청구항은_혼자_단위가_되고_확인되지_않음(caplog):
    splits = {**SPLITS, 2: split(2, ["투명한 재질"], None)}
    with caplog.at_level(logging.WARNING):
        units, _ = _units([rejection(1, "29-2", [1, 2, 3])], splits)
    by_id = {u.unit_id: u for u in units}
    assert set(by_id) == {"oa_1:29-2:c1", "oa_1:29-2:c2", "oa_1:29-2:c3"}
    assert by_id["oa_1:29-2:c1"].claims == [1]
    assert by_id["oa_1:29-2:c1"].status.value == StatusValue.CONFIRMED
    for unit_id in ("oa_1:29-2:c2", "oa_1:29-2:c3"):  # 3은 2를 거쳐야 해서 같이 못 정한다
        unit = by_id[unit_id]
        assert unit.status.value == StatusValue.UNVERIFIED
        assert unit.status.reason == UnverifiedReason.INPUT_UNVERIFIED
        assert Flag.NEEDS_HUMAN_REVIEW in unit.flags
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_나눈_결과가_없는_청구항도_혼자_단위로_남긴다():
    units, _ = _units([rejection(1, "29-2", [1, 9])])
    by_id = {u.unit_id: u for u in units}
    assert by_id["oa_1:29-2:c9"].status.reason == UnverifiedReason.INPUT_UNVERIFIED


def test_지원_안_하는_거절이유와_대상_청구항을_모르는_거절이유는_단위를_만들지_않는다(caplog):
    with caplog.at_level(logging.WARNING):
        units, held = _units([rejection(1, "45", [1]), rejection(2, "29-2", None)])
    assert units == []
    assert [h.task for h in held] == ["f3_units:oa_1:r2"]  # 못 만든 것은 보류로 남긴다
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_같은_조문_같은_대표_청구항이_또_나오면_보류로_남긴다():
    units, held = _units([rejection(1, "29-2", [1]), rejection(2, "29-2", [1, 2])])
    assert [u.unit_id for u in units] == ["oa_1:29-2:c1"]
    assert units[0].rejection == 1
    assert [h.task for h in held] == ["f3_units:oa_1:r2:c1"]
