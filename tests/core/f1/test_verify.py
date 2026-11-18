"""원문 대조·합치기와 지원 조문·나라 판정 테스트. 글자는 모두 지어낸 것 (실제 통지서 아님)."""

from patent_ai.core.f1_oa_reader.support import SUPPORTED_ARTICLES, country_of, is_supported
from patent_ai.core.f1_oa_reader.verify import Found, merge, raw_text_on_page
from patent_ai.core.schemas.common import Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.document import Page, PageText


def _pages(*texts: str) -> PageText:
    ok = Status(value=StatusValue.CONFIRMED, checked="글자 있음")
    return PageText(
        document_id="d_1",
        pages=[Page(page=i, text=t, status=ok) for i, t in enumerate(texts, start=1)],
        status=ok,
    )


PAGES = _pages("출원번호 10-2099-0000001\n발송번호 9-5-2099-000001", "제출기일 2099.12.31")


# ---- raw_text_on_page ----
def test_공백과_줄바꿈만_달라도_원문에_있다고_본다():
    assert raw_text_on_page(PAGES, 1, "발송번호 9-5-2099-000001")
    assert raw_text_on_page(PAGES, 1, "출원번호\n10-2099-0000001")


def test_없는_글자나_없는_쪽_번호는_False():
    assert not raw_text_on_page(PAGES, 2, "10-2099-0000001")  # 다른 쪽에 있는 글자
    assert not raw_text_on_page(PAGES, 1, "10-2099-9999999")  # 원문에 없는 글자
    assert not raw_text_on_page(PAGES, 3, "제출기일")  # 없는 쪽
    assert not raw_text_on_page(PAGES, 0, "제출기일")


# ---- merge ----
def test_규칙과_모델이_같은_값이면_confirmed():
    f = Found("10-2099-0000001", "10-2099-0000001", 1)
    r = merge(f, Found("10-2099-0000001", "10-2099-0000001", 1), PAGES)
    assert r.status.value == StatusValue.CONFIRMED
    assert r.status.checked == "1쪽 원문 대조"
    assert (r.value, r.raw_text, r.page) == ("10-2099-0000001", "10-2099-0000001", 1)


def test_둘_다_없으면_not_extracted():
    r = merge(None, None, PAGES)
    assert r.status.value == StatusValue.UNVERIFIED
    assert r.status.reason == UnverifiedReason.NOT_EXTRACTED
    assert r.value is None and r.page is None and r.raw_text is None


def test_원문에_없는_글자는_값과_쪽을_버린다():
    r = merge(None, Found("10-2099-9999999", "10-2099-9999999", 1), PAGES)
    assert r.status.reason == UnverifiedReason.NOT_EXTRACTED
    assert r.value is None and r.page is None and r.raw_text is None


def test_다른_쪽_번호를_대면_대조_실패():
    r = merge(Found("10-2099-0000001", "10-2099-0000001", 2), None, PAGES)
    assert r.status.value == StatusValue.UNVERIFIED
    assert r.page is None


def test_쪽이_없는_값은_대조_실패():
    r = merge(Found("10-2099-0000001", "10-2099-0000001", None), None, PAGES)
    assert r.status.reason == UnverifiedReason.NOT_EXTRACTED


def test_하나만_대조_통과하면_그_값():
    good = Found("10-2099-0000001", "10-2099-0000001", 1)
    bad = Found("10-2099-7777777", "10-2099-7777777", 1)
    r = merge(good, bad, PAGES)
    assert r.status.value == StatusValue.CONFIRMED
    assert r.value == "10-2099-0000001"
    r2 = merge(bad, None, PAGES)
    assert r2.status.reason == UnverifiedReason.NOT_EXTRACTED


def test_둘이_다르면_conflict와_후보_둘():
    rule = Found("10-2099-0000001", "10-2099-0000001", 1)
    model = Found("9-5-2099-000001", "9-5-2099-000001", 1)
    r = merge(rule, model, PAGES)
    assert r.status.value == StatusValue.CONFLICT
    assert r.value is None and r.page is None
    assert [(c.source, c.value, c.page) for c in r.candidates] == [
        ("rule", "10-2099-0000001", 1),
        ("model", "9-5-2099-000001", 1),
    ]


def test_ambiguous는_값을_비우고_대조_통과할_때만_글자와_쪽을_남긴다():
    r = merge(None, Found("x", "10-2099-0000001", 1, ambiguous=True), PAGES)
    assert r.status.reason == UnverifiedReason.AMBIGUOUS
    assert r.value is None
    assert (r.raw_text, r.page) == ("10-2099-0000001", 1)
    r2 = merge(None, Found("x", "원문에 없음", 1, ambiguous=True), PAGES)
    assert r2.status.reason == UnverifiedReason.AMBIGUOUS
    assert r2.raw_text is None and r2.page is None


def test_날짜처럼_글자만_비교하면_value_없이_raw_text와_쪽을_남긴다():
    rule = Found(None, "2099.12.31", 2)
    model = Found(None, "2099.\n12.31", 2)
    r = merge(rule, model, PAGES, compare_by="raw_text")
    assert r.status.value == StatusValue.CONFIRMED
    assert r.value is None
    assert (r.raw_text, r.page) == ("2099.12.31", 2)
    r2 = merge(rule, Found(None, "2099.12", 2), PAGES, compare_by="raw_text")
    assert r2.status.value == StatusValue.CONFLICT


# ---- support ----
def test_지원_조문은_셋만():
    assert SUPPORTED_ARTICLES == {"29-1-1", "29-1-2", "29-2", "42-4-2"}
    for a in ("29-1-1", "29-1-2", "29-2", "42-4-2"):
        assert is_supported(a)
    # 호가 없는 29-1(산업상 이용가능성과 구분 안 됨)·다른 조문은 지원 안 함
    for a in ("29-1", "29-3", "42-4-1", "42-4", "36-1", ""):
        assert not is_supported(a)


def test_나라는_표기_정규식으로_정한다():
    cases = {
        "공개특허공보 제10-2099-0000001호": "KR",
        "등록특허공보 제10-0000001호": "KR",
        "KR 10-2099-0000001": "KR",
        "US 2099/0000001": "US",
        "US 1,234,567": "US",
        "미국 공개특허 2099/0000001": "US",
        "JP 2099-000001": "JP",
        "CN 100000001": "CN",
        "EP 1000001": "EP",
        "WO 2099/000001": "WO",
        "일본 공개특허공보 2099-000001": "JP",
        "중국 공개특허 100000001": "CN",
    }
    for text, country in cases.items():
        r = country_of(text, 3)
        assert r.value == country, text
        assert r.status.value == StatusValue.CONFIRMED
        assert (r.raw_text, r.page) == (text, 3)


def test_나라_표기가_맞는_것이_없으면_ambiguous():
    r = country_of("참고문헌 1", 2)
    assert r.value is None
    assert r.status.value == StatusValue.UNVERIFIED
    assert r.status.reason == UnverifiedReason.AMBIGUOUS


def test_빈_글자는_쪽도_글자도_비운다():
    r = country_of("  ", 2)
    assert r.value is None and r.page is None and r.raw_text is None
    assert r.status.reason == UnverifiedReason.AMBIGUOUS


# ---- 검토 반영 ----
def test_값이_원문_글자에_없으면_그쪽을_버린다():
    # 글자는 원문에 있지만(1쪽의 "1") 값은 글자에서 나온 게 아님
    r = merge(Found("10-9999-1111111", "1", 1), None, PAGES)
    assert r.status.reason == UnverifiedReason.NOT_EXTRACTED
    assert r.value is None


def test_derive가_있으면_원문_글자에서_값을_다시_뽑는다():
    pages = _pages("거절이유 제1항 내지 제3항")

    def claims(text: str):
        return [1, 2, 3] if "제1항 내지 제3항" in text else None

    r = merge(None, Found([9], "제1항 내지 제3항", 1), pages, derive=claims)  # 넘어온 value는 무시
    assert r.value == [1, 2, 3]
    assert r.status.value == StatusValue.CONFIRMED
    # derive가 None을 내면 그쪽은 못 씀
    r2 = merge(None, Found([1], "거절이유", 1), pages, derive=claims)
    assert r2.status.reason == UnverifiedReason.NOT_EXTRACTED


def test_한쪽이라도_ambiguous면_다른_쪽이_통과해도_확인되지_않음():
    good = Found("10-2099-0000001", "10-2099-0000001", 1)
    amb = Found("x", "발송번호 9-5-2099-000001", 1, ambiguous=True)
    r = merge(good, amb, PAGES)
    assert r.status.reason == UnverifiedReason.AMBIGUOUS
    assert r.value is None
    assert (r.raw_text, r.page) == ("발송번호 9-5-2099-000001", 1)  # ambiguous 쪽 우선
    r2 = merge(amb, good, PAGES)
    assert r2.status.reason == UnverifiedReason.AMBIGUOUS
    assert r2.raw_text == "발송번호 9-5-2099-000001"
    # ambiguous 쪽 대조 실패면 통과한 다른 쪽 글자
    bad_amb = Found("x", "원문에 없음", 1, ambiguous=True)
    r3 = merge(good, bad_amb, PAGES)
    assert r3.status.reason == UnverifiedReason.AMBIGUOUS
    assert (r3.raw_text, r3.page) == ("10-2099-0000001", 1)


def test_한쪽을_버리면_로그_한_줄이고_글자는_찍지_않는다(caplog):
    good = Found("10-2099-0000001", "10-2099-0000001", 1)
    bad = Found("10-2099-7777777", "10-2099-7777777", 1)
    with caplog.at_level("INFO", logger="patent_ai.core.f1_oa_reader.verify"):
        r = merge(good, bad, PAGES, field="출원번호")
    assert r.candidates == []
    logs = [m for m in caplog.messages if "출원번호" in m]
    assert len(logs) == 1
    assert "7777777" not in logs[0]


def test_나라_표기가_둘_섞이면_ambiguous():
    r = country_of("US 2099/0000001, JP 2099-000001", 1)
    assert r.value is None
    assert r.status.reason == UnverifiedReason.AMBIGUOUS
    assert (r.raw_text, r.page) == ("US 2099/0000001, JP 2099-000001", 1)
