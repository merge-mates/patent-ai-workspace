"""사건 자료 묶기 규칙 테스트 (#16). 번호는 모두 지어낸 것 (2099년 값, 실제 사건 아님)."""

import pytest

from patent_ai.core.f1_oa_reader.case_grouping import normalize_receipt_number, read_number
from patent_ai.core.schemas.common import StatusValue, UnverifiedReason

# --- T1 번호 읽기·정규화 -------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "1-1-2099-0000001-12",  # 하이픈 있음
        "112099000000112",  # 하이픈 없음
        "접수번호: 1-1-2099-0000001-12 ",  # 이름표·공백이 붙음
    ],
)
def test_number_접수번호_꼴이면_숫자_15자리(text):
    assert normalize_receipt_number(text) == "112099000000112"


@pytest.mark.parametrize(
    "text",
    [
        "",  # 빈 글자
        "1-1-2099-0000001",  # 끝 두 자리 없음
        "1-1-2099-000001-12",  # 가운데 자리 수 모자람
        "1-1-2099-0000001-123",  # 끝 자리 수 넘침
        "21-1-2099-0000001-12",  # 앞에 숫자가 더 붙음
        "9-5-2099-012345678",  # 발송번호 꼴
        "10-2099-0001234",  # 출원번호 꼴
    ],
)
def test_number_접수번호_꼴이_아니면_None(text):
    assert normalize_receipt_number(text) is None


@pytest.mark.parametrize(
    ("kind", "text", "value"),
    [
        ("application", "10-2099-0001234", "1020990001234"),
        ("dispatch", "9-5-2099-012345678", "952099012345678"),
        ("receipt", "1-1-2099-0000001-12", "112099000000112"),
    ],
)
def test_number_읽으면_confirmed_원문_글자_그대로(kind, text, value):
    v = read_number(kind, text)
    assert v.value == value
    assert v.raw_text == text  # 원문 글자는 정규화하지 않고 그대로
    assert v.status.value == StatusValue.CONFIRMED


@pytest.mark.parametrize(
    ("kind", "text"),
    [
        ("application", "10-2099-001234"),  # 자리 수 틀림
        ("dispatch", "1-1-2099-0000001-12"),  # 접수번호를 발송번호 칸에
        ("receipt", "9-5-2099-012345678"),  # 발송번호를 접수번호 칸에
    ],
)
def test_number_못_읽으면_unverified_값_없음_글자는_남김(kind, text):
    v = read_number(kind, text)
    assert v.value is None
    assert v.raw_text == text  # 사람이 볼 수 있게 글자는 남긴다
    assert v.status.value == StatusValue.UNVERIFIED
    assert v.status.reason == UnverifiedReason.NOT_EXTRACTED


@pytest.mark.parametrize("text", [None, "", "   "])
def test_number_번호_글자가_없으면_unverified_글자도_없음(text):
    v = read_number("application", text)
    assert v.value is None
    assert v.raw_text is None
    assert v.status.reason == UnverifiedReason.NOT_EXTRACTED
