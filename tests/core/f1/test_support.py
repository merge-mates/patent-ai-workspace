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
    ("raw", "expected"),
    [
        # 2.3: 종류 코드가 원문에 있으면 그대로
        ("US 7,123,456 B1", "US7123456B1"),
        ("US 10,123,456 B2", "US10123456B2"),
        ("US 2020/0123456 A1", "US20200123456A1"),
        # 2.3: 코드가 없으면 미국 등록은 코드 없이 (B1·B2는 번호로 못 가림)
        ("US 7,123,456", "US7123456"),
        ("US 10,123,456", "US10123456"),
        ("US7123456", "US7123456"),
        # 2.3: 코드가 없으면 미국 공개(연도/7자리)는 A1
        ("US 2020/0123456", "US20200123456A1"),
        ("미국공개특허공보 US2020/0123456호", "US20200123456A1"),
        ("US 2020/0123456 (2020.04.23.)", "US20200123456A1"),
    ],
)
def test_미국_인용_키는_코드가_없어도_정답_꼴(raw, expected):
    assert citation_key(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "KR10-0000001",  # 옛 표기: 꼴을 못 정함
        "JP2020-123456",  # 일본은 종류 코드가 없으면 지어내지 않는다
        "US 123456",  # 미국 등록 번호 꼴(7·8자리)이 아님
        "US 2020/0123456 A1, US 7,123,456 B2",  # 키가 둘
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
