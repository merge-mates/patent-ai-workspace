"""F2 task-1: 조문 코드·OA 발송일 꼴 맞추기 (코드 도구, 모델 안 씀)."""

from datetime import date

import pytest

from patent_ai.core.f2_legal_research.refs import (
    ArticleRef,
    article_ref,
    article_refs_in_text,
    parse_dispatch_date,
)


@pytest.mark.parametrize(
    ("code", "jo", "hang", "ho", "loc", "label"),
    [
        ("29-2", 29, 2, None, 290002, "특허법 제29조제2항"),
        ("29-1-1", 29, 1, 1, 290001, "특허법 제29조제1항제1호"),
        ("42-4-2", 42, 4, 2, 420004, "특허법 제42조제4항제2호"),
    ],
)
def test_조문_코드를_색인_위치로(code, jo, hang, ho, loc, label):
    ref = article_ref(code)
    assert ref == ArticleRef(law="특허법", jo=jo, gaji=0, hang=hang, ho=ho, label=label)
    assert ref.loc == loc


def test_같은_항의_호_여럿은_항_하나로_합친다():
    ref = article_ref("29-1-1|29-1-2")
    assert ref is not None
    assert (ref.loc, ref.ho, ref.label) == (290001, None, "특허법 제29조제1항")


@pytest.mark.parametrize("code", [None, "", "29", "가-2", "29-2|42-4-2", "29-0", "29-2-x"])
def test_꼴이_다르거나_항이_다르면_None(code):
    assert article_ref(code) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2099.01.26.", date(2099, 1, 26)),
        ("2020. 5. 4.", date(2020, 5, 4)),
        ("2020-05-04", date(2020, 5, 4)),
        ("발송일자 2020.05.04", date(2020, 5, 4)),
    ],
)
def test_발송일_글자를_날짜로(raw, expected):
    assert parse_dispatch_date(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "날짜 없음", "2020.02.30."])
def test_발송일을_못_읽으면_None(raw):
    assert parse_dispatch_date(raw) is None


def _labels(text):
    return [r.label for r in article_refs_in_text(text)]


def test_글_속_조문_세_꼴을_읽는다():
    assert _labels("특허법 제29조제2항이 뭔가요") == ["특허법 제29조제2항"]
    assert _labels("제42조 제4항 제2호는?") == ["특허법 제42조제4항제2호"]  # 법 이름 없으면 특허법
    assert _labels("29조 2항 알려줘") == ["특허법 제29조제2항"]
    ref = article_refs_in_text("제42조 제4항 제2호")[0]
    assert (ref.jo, ref.hang, ref.ho, ref.loc) == (42, 4, 2, 420004)


def test_다른_법_이름이_붙은_조문은_버린다():
    assert _labels("특허법 시행령 제5조제1항") == []
    assert _labels("실용신안법 제4조제2항") == []
    assert _labels("실용신안법 제4조제2항과 특허법 제29조제2항") == ["특허법 제29조제2항"]


def test_같은_조_항은_하나로_합친다():
    assert _labels("특허법 제29조제2항, 29조 2항, 제42조제4항") == [
        "특허법 제29조제2항",
        "특허법 제42조제4항",
    ]


def test_조문_번호가_없으면_빈_목록():
    assert article_refs_in_text("진보성이 뭔가요") == []


def test_방법_같은_일반어는_법_이름으로_보지_않는다():
    assert _labels("진보성 판단 방법 29조 2항") == ["특허법 제29조제2항"]
    assert _labels("판단방법 제29조제2항") == ["특허법 제29조제2항"]


@pytest.mark.parametrize(
    ("text", "labels"),
    [
        # PR #316 리뷰의 재현 셋: 뒤 조문도 앞에 나온 다른 법의 조문이다
        ("실용신안법 제4조제1항, 제5조제1항", []),
        ("실용신안법 제4조제1항 및 같은 법 제5조제1항", []),
        ("특허법 시행령 제5조제1항 및 제6조제1항", []),
        # "동법"도 앞 법을 따른다
        ("실용신안법 제4조제1항 및 동법 제5조제1항", []),
        ("특허법 제29조제2항 및 동법 제42조제4항", ["특허법 제29조제2항", "특허법 제42조제4항"]),
        ("특허법 제29조제2항, 같은 법 시행령 제5조제1항", ["특허법 제29조제2항"]),
        # "같은 법"은 시행령이 아니라 그 법이다
        ("특허법 시행령 제5조제1항 및 같은 법 제29조제2항", ["특허법 제29조제2항"]),
        # 다음 법 이름이 나오면 그 법으로 바뀐다 (토씨가 붙어도)
        (
            "실용신안법 제4조제1항, 특허법 제29조제2항, 제42조제4항",
            ["특허법 제29조제2항", "특허법 제42조제4항"],
        ),
        ("실용신안법에서 제4조제1항, 특허법의 제29조제2항", ["특허법 제29조제2항"]),
        # 일반어는 법을 바꾸지 않는다
        (
            "특허법 제29조제2항의 판단 방법 제42조제4항",
            ["특허법 제29조제2항", "특허법 제42조제4항"],
        ),
    ],
)
def test_법_이름은_다음_법_이름이_나올_때까지_이어진다(text, labels):
    assert _labels(text) == labels
