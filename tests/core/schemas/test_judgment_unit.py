"""JudgmentUnit(②) 테스트. 기대값은 이슈 #164 설계와 docs/data-model.md 3절."""

import pytest
from pydantic import ValidationError

from patent_ai.core.schemas.common import Status
from patent_ai.core.schemas.judgment_unit import JudgmentUnit, UnitKind

OK = Status(value="confirmed", checked="청구항 원문 대조")


def unit(**kw):
    data = {
        "status": OK,
        "unit_id": "oa_1:29-2:c1",
        "rejection": 1,
        "rejection_kind": "inventive_step",
        "unit_kind": "independent_group",
        "representative_claim": 1,
        "claims": [1, 2, 3],
        "order": 1,
    }
    data.update(kw)
    return JudgmentUnit(**data)


@pytest.mark.parametrize(
    ("kind", "unit_kind", "article"),
    [
        ("inventive_step", "independent_group", "29-2"),
        ("novelty", "independent_group", "29-1-1"),
        ("clarity", "single_claim", "42-4-2"),
    ],
)
def test_거절이유_종류별_단위_종류(kind, unit_kind, article):
    claims = [1] if kind == "clarity" else [1, 2, 3]  # 명확성은 청구항 하나
    u = unit(rejection_kind=kind, unit_kind=unit_kind, unit_id=f"oa_1:{article}:c1", claims=claims)
    assert u.unit_kind == UnitKind(unit_kind)
    assert u.read_with == []
    assert u.parent_unit_id is None


@pytest.mark.parametrize(
    ("kind", "unit_kind"),
    [
        ("clarity", "independent_group"),
        ("inventive_step", "single_claim"),
        ("novelty", "single_claim"),
    ],
)
def test_종류와_단위_종류가_어긋나면_거부(kind, unit_kind):
    with pytest.raises(ValidationError):
        unit(rejection_kind=kind, unit_kind=unit_kind)


def test_other는_판단_단위를_만들지_않는다():
    with pytest.raises(ValidationError):
        unit(rejection_kind="other")


def test_명확성은_함께_읽을_청구항을_가진다():
    u = unit(
        rejection_kind="clarity",
        unit_kind="single_claim",
        unit_id="oa_1:42-4-2:c3",
        representative_claim=3,
        claims=[3],
        read_with=[1],
    )
    assert u.read_with == [1]


def test_명확성이_아닌데_read_with가_있으면_거부():
    with pytest.raises(ValidationError):
        unit(read_with=[1])


@pytest.mark.parametrize(
    "claims",
    [[], [1, 1, 2], [2, 3]],
    ids=["빈 목록", "중복", "대표 청구항 없음"],
)
def test_claims_검사(claims):
    with pytest.raises(ValidationError):
        unit(claims=claims)


@pytest.mark.parametrize(
    "unit_id",
    ["oa_1", "oa_1:29-2:1", "oa_1:29-2:c2", "oa_1:29-2:c1/", "oa_1:29-2:c1/A", "oa_1:c1"]
    + ["oa_1:|:c1", "oa_1:-:c1", "oa_1:29||2:c1", "oa_1:29-:c1", "oa_1:|29-2:c1"],
)
def test_unit_id_꼴이_틀리면_거부(unit_id):
    with pytest.raises(ValidationError):
        unit(unit_id=unit_id)


def test_호가_여럿이면_바_로_잇는_조문은_통과():
    u = unit(rejection_kind="novelty", unit_id="oa_1:29-1-1|29-1-2:c1")
    assert u.unit_id.endswith("c1")


def test_명확성은_청구항_하나만_담는다():
    base = {
        "rejection_kind": "clarity",
        "unit_kind": "single_claim",
        "unit_id": "oa_1:42-4-2:c3",
        "representative_claim": 3,
    }
    with pytest.raises(ValidationError):
        unit(**base, claims=[3, 4])
    with pytest.raises(ValidationError):
        unit(**base, claims=[3], read_with=[3])


def test_하위_단위는_부모_id로_시작():
    u = unit(unit_id="oa_1:29-2:c1/a", parent_unit_id="oa_1:29-2:c1")
    assert u.parent_unit_id == "oa_1:29-2:c1"
    deeper = unit(unit_id="oa_1:29-2:c1/a/b", parent_unit_id="oa_1:29-2:c1/a")
    assert deeper.unit_id.endswith("/b")


def test_부모_id로_시작하지_않으면_거부():
    with pytest.raises(ValidationError):
        unit(unit_id="oa_1:29-2:c1", parent_unit_id="oa_1:29-2:c1")
    with pytest.raises(ValidationError):
        unit(unit_id="oa_1:29-2:c1/a", parent_unit_id="oa_2:29-2:c1")


def test_모르는_칸은_거부():
    with pytest.raises(ValidationError):
        unit(search_index="x")


def test_왕복():
    u = unit(unit_id="oa_1:29-2:c1/a", parent_unit_id="oa_1:29-2:c1")
    dumped = u.model_dump(mode="json")
    assert JudgmentUnit.model_validate(dumped) == u
    assert dumped["unit_kind"] == "independent_group"
