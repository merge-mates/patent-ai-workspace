"""규칙 추출 테스트. 통지서 글자는 모두 지어낸 것 (2099년 값, 실제 통지서 아님)."""

import pytest

from patent_ai.core.f1_oa_reader.rules import (
    expand_claims,
    extract_by_rules,
    normalize_application_number,
    normalize_article,
    normalize_dispatch_number,
    notice_kind_of,
    parse_cited_locations,
    parse_same_as,
    quoted_segments,
)
from patent_ai.core.f1_oa_reader.verify import Found
from patent_ai.core.schemas.common import Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.document import Page, PageText
from patent_ai.core.schemas.oa_result import NoticeKind


def _pages(*texts: str) -> PageText:
    """글자 목록으로 PageText를 만든다 (빈 글자 쪽은 글자 층 없음)."""
    pages = []
    for n, t in enumerate(texts, start=1):
        if t:
            st = Status(value=StatusValue.CONFIRMED, checked="테스트")
        else:
            st = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.BODY_MISSING)
        pages.append(Page(page=n, text=t, status=st))
    doc = Status(value=StatusValue.CONFIRMED, checked="테스트")
    return PageText(document_id="d1", pages=pages, status=doc)


HEADER = (
    "의견제출통지서\n"
    "출원번호 10-2099-0001234\n"
    "발송번호 9-5-2099-012345678\n"
    "발송일자 2099.01.26.\n"
    "제출기일 2099.03.26.\n"
    "거절이유 내용은 아래와 같습니다.\n"
)


# ---- extract_by_rules ----
def test_번호와_날짜_글자를_뽑는다():
    f = extract_by_rules(_pages(HEADER))
    assert f.application_number == Found(
        value="1020990001234", raw_text="10-2099-0001234", page=1, ambiguous=False
    )
    assert f.dispatch_number is not None
    assert f.dispatch_number.value == "952099012345678"
    # 날짜는 값으로 바꾸지 않고 글자 그대로 (value는 비움)
    assert f.notice_date is not None
    assert f.notice_date.value is None
    assert f.notice_date.raw_text == "2099.01.26."
    assert f.notice_date.page == 1
    assert f.response_due is not None
    assert f.response_due.raw_text == "2099.03.26."


def test_하이픈_없는_출원번호도_숫자만_값으로_글자는_그대로():
    f = extract_by_rules(_pages("출원번호 1020990001234\n"))
    assert f.application_number is not None
    assert f.application_number.value == "1020990001234"
    assert f.application_number.raw_text == "1020990001234"


def test_둘째_쪽에서도_찾고_쪽_번호를_남긴다():
    f = extract_by_rules(_pages("의견제출통지서", "발송일자 2099.01.26."))
    assert f.notice_date is not None
    assert f.notice_date.page == 2


def test_인용문헌의_번호는_출원번호로_뽑지_않는다():
    f = extract_by_rules(_pages("인용발명 공개특허공보 제10-2098-0007654호\n"))
    assert f.application_number is None


def test_같은_칸에_다른_번호가_둘이면_ambiguous():
    f = extract_by_rules(_pages("출원번호 10-2099-0001234\n출원번호 10-2099-0005678\n"))
    assert f.application_number is not None
    assert f.application_number.ambiguous is True
    assert f.application_number.value == "1020990001234"


def test_빈_쪽과_쪽_없음은_모두_None():
    for pt in (_pages(""), _pages()):
        f = extract_by_rules(pt)
        assert f.application_number is None
        assert f.dispatch_number is None
        assert f.notice_date is None
        assert f.response_due is None


def test_깨진_번호는_지어내지_않는다():
    f = extract_by_rules(_pages("출원번호 10-2099-00\n발송일자 2099.01.\n"))
    assert f.application_number is None
    assert f.notice_date is None


# ---- normalize_article ----
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("특허법 제29조제2항", "29-2"),
        ("특허법 제29조 제1항", "29-1"),
        ("특허법 제42조제4항제2호", "42-4-2"),
        ("특허법 제42조 제4항 제2호", "42-4-2"),
        ("제29조", "29"),
    ],
)
def test_조문을_번호로_바꾼다(text, expected):
    assert normalize_article(text) == expected


@pytest.mark.parametrize(
    "text", ["", "특허법", "특허법 제A조제2항", "특허법 제29조제항", "제29조제B항"]
)
def test_깨진_조문은_None(text):
    assert normalize_article(text) is None


# ---- expand_claims ----
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("제1항 내지 제4항, 제6항", [1, 2, 3, 4, 6]),
        ("제1-20항", list(range(1, 21))),
        ("제1-4, 6-20항", [1, 2, 3, 4, *range(6, 21)]),
        ("청구항 제1항", [1]),
        ("청구항 제1항 내지 제3항 및 제5항", [1, 2, 3, 5]),
        ("제3항, 제1항, 제3항", [1, 3]),
    ],
)
def test_청구항_범위를_펼친다(text, expected):
    assert expand_claims(text) == expected


@pytest.mark.parametrize(
    "text", ["", "청구항", "제1항 내지 제A항", "제5-3항", "제1항 그리고 제2항"]
)
def test_애매한_청구항은_None(text):
    assert expand_claims(text) is None


# ---- notice_kind_of ----
def test_최후_표시가_있으면_final과_원문_쪽():
    k = notice_kind_of(_pages("최후거절이유통지서\n출원번호 10-2099-0001234\n"))
    assert k.value == NoticeKind.FINAL
    assert k.raw_text == "최후거절이유통지"
    assert k.page == 1
    assert k.status.value == StatusValue.CONFIRMED


def test_머리말을_읽었는데_표시가_없으면_initial():
    k = notice_kind_of(_pages(HEADER))
    assert k.value == NoticeKind.INITIAL
    assert k.raw_text is None
    assert k.page is None
    assert k.status.value == StatusValue.CONFIRMED
    assert k.status.checked == "최후 표시 없음, 모든 쪽 글자를 봄"


def test_머리말_잘림은_unknown과_not_extracted():
    # 1쪽에 통지서 제목(의견제출통지서)이 없음
    k = notice_kind_of(_pages("특허청"))
    assert k.value == NoticeKind.UNKNOWN
    assert k.status.value == StatusValue.UNVERIFIED
    assert k.status.reason == UnverifiedReason.NOT_EXTRACTED


def test_빈_쪽과_쪽_없음은_unknown():
    for pt in (_pages(""), _pages()):
        k = notice_kind_of(pt)
        assert k.value == NoticeKind.UNKNOWN
        assert k.status.reason == UnverifiedReason.NOT_EXTRACTED


def test_최후_표시가_둘째_쪽에만_있으면_final_쪽_2():
    k = notice_kind_of(_pages(HEADER, "본문\n최후거절이유통지"))
    assert k.value == NoticeKind.FINAL
    assert k.page == 2
    assert k.raw_text == "최후거절이유통지"


def test_1쪽_16줄째의_최후_표시도_final():
    text = HEADER + "\n".join(f"줄{i}" for i in range(12)) + "\n최후 거절이유\n통지"
    assert len(text.splitlines()) > 15
    k = notice_kind_of(_pages(text))
    assert k.value == NoticeKind.FINAL
    assert k.page == 1


def test_띄어_쓴_제목도_머리말을_읽은_것():
    k = notice_kind_of(_pages("의 견 제 출 통 지 서\n출원번호 10-2099-0001234"))
    assert k.value == NoticeKind.INITIAL
    assert k.status.checked == "최후 표시 없음, 모든 쪽 글자를 봄"


def test_본문에_거절이유통지_안내만_있고_제목_없으면_unknown():
    k = notice_kind_of(_pages("거절이유통지에 대한 안내\n출원번호 10-2099-0001234"))
    assert k.value == NoticeKind.UNKNOWN
    assert k.status.reason == UnverifiedReason.NOT_EXTRACTED


@pytest.mark.parametrize("text", ["특허법 제29조의2", "특허법 제29조의2 제1항"])
def test_조의N은_None(text):
    assert normalize_article(text) is None


def test_제29조제1항제1호는_그대로():
    assert normalize_article("제29조제1항제1호") == "29-1-1"


# ---- 본문 속 언급은 표시가 아니다 ----
@pytest.mark.parametrize(
    "sentence",
    ["최후거절이유통지에 해당하지 않음", "앞선 최후거절이유통지에 대한 보정"],
)
def test_본문_속_최후거절이유통지_언급은_initial(sentence):
    k = notice_kind_of(_pages(HEADER, sentence))
    assert k.value == NoticeKind.INITIAL


def test_꺾쇠로_감싼_표시는_final():
    k = notice_kind_of(_pages(HEADER + "[최후거절이유통지]\n"))
    assert k.value == NoticeKind.FINAL
    assert k.raw_text == "최후거절이유통지"


def test_제목_줄_괄호_안_표시는_final():
    k = notice_kind_of(_pages("의견제출통지서 (최후거절이유통지)\n출원번호 10-2099-0001234\n"))
    assert k.value == NoticeKind.FINAL
    assert k.page == 1


# ---- 번호 값 꼴: 하이픈 없는 숫자 (정답 형식 f1-oa-gold.md 4절) ----
def test_출원번호_값은_하이픈_없는_숫자():
    assert normalize_application_number("출원번호 10-2099-0000001") == "1020990000001"
    assert normalize_application_number("1020990000001") == "1020990000001"
    assert normalize_application_number("10-2099-00") is None


def test_발송번호_값은_숫자만():
    assert normalize_dispatch_number("9-5-2099-000000001") == "952099000000001"
    assert normalize_dispatch_number("952099000000001") == "952099000000001"
    assert normalize_dispatch_number("9-5-2099") is None


# ---- 호가 여럿인 조문 ----
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("특허법 제29조제1항제1호 및 제2호", "29-1-1|29-1-2"),
        ("특허법 제29조 제1항 제1호, 제2호", "29-1-1|29-1-2"),
        ("특허법 제42조제4항제1호 및 제2호", "42-4-1|42-4-2"),
    ],
)
def test_호가_여럿이면_세로줄로_잇는다(text, expected):
    assert normalize_article(text) == expected


@pytest.mark.parametrize(
    "text", ["제29조제1호 및 제2호", "제29조제1항제A호 및 제2호", "제1호 및 제2호"]
)
def test_호가_여럿이어도_조나_항이_깨졌으면_None(text):
    assert normalize_article(text) is None


# ---- 식별번호(인용 위치) 값 꼴 ----
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("식별번호 [0023], [0031]", ["[0023]", "[0031]"]),
        ("[16, 38, 78]", ["[0016]", "[0038]", "[0078]"]),
        ("[0080]-[0081]", ["[0080]-[0081]"]),
        ("[0080-0081]", ["[0080]-[0081]"]),  # 이 꼴로는 안 내보낸다
        ("[80~81]", ["[0080]-[0081]"]),
        ("[0014], [0056], 도 4b", ["[0014]", "[0056]", "도 4b"]),
        ("도 4c", ["도 4c"]),
        ("도4c", ["도 4c"]),
        ("청구항 9", ["청구항 9"]),
        ("청구항 제9항", ["청구항 9"]),
        ("요약", ["요약"]),
        ("3:5-10", ["3:5-10"]),
        ("col. 3, ll. 5-10", ["3:5-10"]),
        ("[0016] 참조", ["[0016]"]),
        ("[0016], 도 4b 등 참조", ["[0016]", "도 4b"]),
        ("도면 2a, 2b", ["도 2a", "도 2b"]),
        ("도 4b 및 4c", ["도 4b", "도 4c"]),
        ("[0014], 도 4b 및 4c, [0056]", ["[0014]", "도 4b", "도 4c", "[0056]"]),
    ],
)
def test_식별번호를_정답_꼴로_바꾼다(raw, expected):
    assert parse_cited_locations(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "식별번호", "[0023], 어딘가", "[0081]-[0080]", "[12345]", "[abc]", "도 4c 내지 도 4f"],
)
def test_못_읽는_조각이_있으면_None_지어내지_않는다(raw):
    assert parse_cited_locations(raw) is None


# ---- #18 task-6: 도면 부호, 같은 취지 대상, 따옴표 안 글자 ----
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("폐곡선(310, 320)", ["폐곡선(310, 320)"]),  # 3절 5: 도면 부호만 -> 그대로
        ("폐곡선(310,320)", ["폐곡선(310,320)"]),
        ("[0014], 폐곡선(310, 320)", ["[0014]", "폐곡선(310, 320)"]),
    ],
)
def test_도면_부호만_짚으면_부호를_그대로_적는다(raw, expected):
    assert parse_cited_locations(raw) == expected


def test_도면_부호_꼴이_아닌_글자는_여전히_None():
    assert parse_cited_locations("폐곡선 어딘가") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("제1항과 동일한 취지", ["claim:1"]),  # 3절 1
        ("청구항 제1항 내지 제3항과 같", ["claim:1", "claim:2", "claim:3"]),  # 3절 2: 펼침
        ("청구항 1, 2는", ["claim:1", "claim:2"]),
        ("거절이유 2와 같고", ["rejection:2"]),  # 3절 3
        ("1-1에서 본 바와 같이", ["rejection:1"]),  # 3절 8
        ("2-3에서 본 바와 같이", ["rejection:2"]),
    ],
)
def test_같은_취지_글자를_대상_목록으로(raw, expected):
    assert parse_same_as(raw) == expected


@pytest.mark.parametrize("raw", ["", "같은 취지", "제A항과 같다", "제1항 내지 제항"])
def test_같은_취지_대상을_못_읽으면_None(raw):
    assert parse_same_as(raw) is None


def test_따옴표_안_글자만_모은다():
    text = "청구항 제6항의 '상기 프리뷰 이미지'는 앞에 정의가 없고 \"약\" 도 불명확합니다."
    assert quoted_segments(text) == ["상기 프리뷰 이미지", "약"]
    assert quoted_segments("모듈들은 장치 구성을 특정할 수 없다") == []
    assert quoted_segments("‘가’와 “나”와 「다」") == ["가", "나", "다"]
