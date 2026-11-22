"""사람 입력 기록 (메모리 fake, 이슈 #70 계획 ②)."""

from datetime import UTC, datetime

import pytest

from patent_ai.core.cases.human_answers import (
    HUMAN_CHECKED,
    InvalidNumberError,
    apply_human_numbers,
    normalize_number,
)
from patent_ai.core.cases.human_inputs import InMemoryHumanInputStore
from patent_ai.core.schemas.common import StatusValue
from tests.core.run_case_fakes import wire

T0 = datetime(2099, 1, 1, tzinfo=UTC)


def test_번호는_실행마다_종류별로_가장_최근_값():
    store = InMemoryHumanInputStore(clock=lambda: T0)
    store.add("oa_1", "r_1", "application_number", "1020990000001")
    store.add("oa_1", "r_1", "application_number", "1020990000002")
    store.add("oa_1", "r_1", "dispatch_number", "952099000000001")
    store.add("oa_1", "r_2", "application_number", "1020990000009")

    assert store.numbers_for_run("r_1") == {
        "application_number": "1020990000002",
        "dispatch_number": "952099000000001",
    }


def test_확인은_그_실행의_정리에만_남고_번호에_섞이지_않는다():
    store = InMemoryHumanInputStore(clock=lambda: T0)
    assert store.confirmed_at("oa_1", "r_1") is None
    at = store.add("oa_1", "r_1", "oa_result_confirmed", None)

    assert store.confirmed_at("oa_1", "r_1") == at == T0
    assert store.confirmed_at("oa_1", "r_2") is None
    assert store.numbers_for_run("r_1") == {}


@pytest.mark.parametrize(
    "kind, value",
    [
        ("application_number", None),
        ("dispatch_number", "  "),
        ("oa_result_confirmed", "x"),
        ("??", "1"),
    ],
)
def test_모양이_틀린_줄은_거부(kind, value):
    store = InMemoryHumanInputStore(clock=lambda: T0)
    with pytest.raises(ValueError):
        store.add("oa_1", "r_1", kind, value)


@pytest.mark.parametrize(
    "kind, text, want",
    [
        ("application_number", "10-2099-0000001", "1020990000001"),
        ("application_number", " 1020990000001 ", "1020990000001"),
        ("dispatch_number", "9-5-2099-000000001", "952099000000001"),
    ],
)
def test_사람이_넣은_번호는_숫자로_맞춘다(kind, text, want):
    assert normalize_number(kind, text) == want


@pytest.mark.parametrize(
    "kind, text",
    [
        ("application_number", "123"),
        ("application_number", "10-2099-0000001, 10-2099-0000002"),  # 둘 이상은 고르지 않는다
        ("dispatch_number", "10-2099-0000001"),
    ],
)
def test_꼴이_아닌_번호는_거부(kind, text):
    with pytest.raises(InvalidNumberError):
        normalize_number(kind, text)


def test_사람_번호를_덮으면_값과_확인_글만_바뀌고_원문_글자는_남는다(monkeypatch):
    oa = wire(monkeypatch)

    out = apply_human_numbers(oa, {"application_number": "1020990000009"})

    app = out.application_number
    assert app.value == "1020990000009" and app.raw_text == oa.application_number.raw_text
    assert app.status.value == StatusValue.CONFIRMED and app.status.checked == HUMAN_CHECKED
    assert out.dispatch_number == oa.dispatch_number
