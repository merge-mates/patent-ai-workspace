"""인용문헌 키 꼴과 지원 조문 테스트 (기대값은 정답 형식 f1-oa-gold.md 2.3절). 번호는 지어낸 값."""

import pytest

from patent_ai.core.f1_oa_reader.support import citation_key, is_supported


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("공개특허공보 제10-2099-0000001호(2099.12.23.)", "KR20990000001A"),
        ("공개특허공보 제10-2099-0000001호", "KR20990000001A"),
        ("등록특허공보 제10-9900001호", "KR109900001B1"),
        ("US 1,234,567 B2", "US1234567B2"),
        ("US 2020/0123456 A1", "US20200123456A1"),
        ("US2020/0123456A1", "US20200123456A1"),
        ("JP 2020-123456 A", "JP2020123456A"),
        ("JP2020-123456A", "JP2020123456A"),
        ("일본공개특허공보 특개2020-123456호", "JP2020123456A"),
        ("일본 공개특허공보 특개2020-123456호(2020.08.20.)", "JP2020123456A"),
        ("일본공표특허공보 특표2020-123456호", "JP2020123456A"),
    ],
)
def test_인용문헌_키는_정답_꼴(raw, expected):
    assert citation_key(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "KR10-0000001",  # 옛 표기: 꼴을 못 정함
        "US 2020/0123456",  # 종류 코드 없음: 지어내지 않는다
        "JP2020-123456",
        "미국공개특허공보 US2020/0123456호",  # "공개"가 있어도 A1로 안 정함
        "Smith, Fake Sensors, 2099 학회",  # 논문(NPL)은 지원 안 함
        "공개특허공보 제10-2099-00호",
    ],
)
def test_꼴을_못_정하면_None(raw):
    assert citation_key(raw) is None


def test_호가_여럿인_조문은_모든_조각이_지원일_때만_지원():
    assert is_supported("29-1-1|29-1-2") is True
    assert is_supported("29-1-1|29-1-3") is False
    assert is_supported("29-1-1|42-3") is False
    assert is_supported("29-2") is True
    assert is_supported("") is False
