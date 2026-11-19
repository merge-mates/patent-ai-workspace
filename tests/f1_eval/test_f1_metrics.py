"""F1 비교 규칙 (eval/f1/metrics.py). 기대값은 정답 형식 문서와 #20 결정에서 왔다."""

import pytest

from eval.f1.metrics import cite_key, clarity_match, norm_text, page_in, same_as_match, text_eq


def test_글자_비교는_공백_줄바꿈만_무시한다():
    assert text_eq("특허법 제29조\n제2항", "특허법 제29조 제2항")
    assert text_eq(None, None)
    assert not text_eq("2099.01.26.", "2099.01.27.")
    assert not text_eq(None, "")
    assert norm_text(" a \t b\n") == "ab"


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("US1234567B2", "US1234567"),  # 미국 등록: 종류 코드 없이 적어도 같음 (#110)
        ("US20200123456A1", "US20200123456"),
        ("KR20990000001A", "KR20990000001"),
        ("KR109900001B1", "KR109900001B2"),
    ],
)
def test_인용_키는_나라와_번호로만_본다(a, b):
    assert cite_key(a) == cite_key(b)


def test_다른_나라나_번호는_다르다():
    assert cite_key("US1234567B2") != cite_key("JP1234567A")
    assert cite_key("KR20990000001A") != cite_key("KR20990000002A")


def test_논문_키는_공백만_무시한다():
    assert cite_key("NPL: 어떤 논문 (학회 2099)") == cite_key("NPL:어떤 논문(학회 2099)")
    assert cite_key(None) is None


def test_명확성_표현은_한쪽이_다른_쪽에_들어_있으면_맞음():
    assert clarity_match(["상기 프리뷰 이미지"], ["프리뷰 이미지"])
    assert clarity_match(["“상기 프리뷰 이미지”"], ["상기프리뷰이미지를"])
    assert not clarity_match(["상기 프리뷰 이미지"], ["다른 표현"])
    assert not clarity_match(["상기 프리뷰 이미지"], [])


def test_따옴표_없는_명확성은_줄만_있으면_맞음():
    # 3절 11번: clarity_terms가 빈 목록이면 그 청구항에 명확성 거절이 있다만 본다
    assert clarity_match([], [])
    assert clarity_match([], ["무엇이든"])


def test_같은_취지는_하나만_겹쳐도_맞음():
    assert same_as_match(["claim:1", "claim:2", "claim:3"], ["claim:2"])
    assert not same_as_match(["claim:1"], ["rejection:1"])
    assert not same_as_match(["claim:1"], [])


def test_줄_쪽은_시작_끝_범위_안이면_맞음():
    assert page_in(3, 4, 4)
    assert page_in(3, None, 3)
    assert not page_in(3, None, 4)
    assert not page_in(3, 4, 5)
    assert not page_in(3, 4, None)
