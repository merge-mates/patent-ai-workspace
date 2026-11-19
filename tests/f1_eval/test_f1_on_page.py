"""원문 위치 대조 (eval/f1/on_page.py). 앱 원문 대조(#125 verify.raw_text_on_page)와 같은 규칙.

1) 그 쪽 글자 2) 그 쪽에서 시작하는 (이어 붙인) 표 칸 3) 그 쪽 + 다음 쪽 본문(머리말·꼬리말 뺌)을
이어 붙여 찾되 시작은 앞 쪽이어야 한다.
"""

from eval.f1.on_page import text_on_page
from patent_ai.core.schemas.common import Status, StatusValue
from patent_ai.core.schemas.document import Page, PageText

OK = Status(value=StatusValue.CONFIRMED, checked="글자 층 있음")
HEAD = ["순번", "거절이유가 있는 부분", "관련 법조항"]


def _pages(*texts: str, tables: dict[int, list] | None = None) -> PageText:
    tables = tables or {}
    return PageText(
        document_id="d",
        pages=[
            Page(page=i, text=t, status=OK, tables=tables.get(i, []))
            for i, t in enumerate(texts, start=1)
        ],
        status=OK,
    )


# 실제 OA처럼 첫 줄 출원번호(머리말), 끝 줄 쪽 번호(꼬리말: `- N -` 또는 `N/M`)
SPLIT = _pages(
    "10-2099-0000001\n"
    "2-1. 청구항 제1항은 인용발명 1의 [0014]에 개시되어 있어 쉽게 발명할 수 있\n"
    "- 3 -",
    "10-2099-0000001\n습니다.\n2-2. 청구항 제2항은 인용발명 2와 같습니다.\n4/6",
)
JUDGMENT = "청구항 제1항은 인용발명 1의 [0014]에 개시되어 있어 쉽게 발명할 수 있습니다."


def test_한_쪽_안의_글자는_공백만_무시하고_통과():
    assert text_on_page(SPLIT, 2, "청구항 제2항은\n인용발명 2와 같습니다.")


def test_두_쪽에_걸친_글자는_머리말_꼬리말을_빼고_시작_쪽으로_통과():
    assert text_on_page(SPLIT, 1, JUDGMENT)
    assert not text_on_page(SPLIT, 2, JUDGMENT)  # 끝 쪽 번호로는 안 됨


def test_통째로_다음_쪽에만_있는_글자는_앞_쪽_번호로_안_됨():
    assert not text_on_page(SPLIT, 1, "청구항 제2항은 인용발명 2와 같습니다.")
    assert not text_on_page(SPLIT, 1, "습니다. 2-2. 청구항 제2항은")


def test_마지막_쪽이면_이어_볼_쪽이_없다():
    assert not text_on_page(SPLIT, 2, "인용발명 2와 같습니다. 청구항 제3항은")


def test_가운데_줄의_출원번호는_빼지_않는다():
    pages = _pages(
        "본문 첫 줄\n10-2099-0000001\n출원의 청구항 제1항은 쉽게 발명할 수 있", "습니다."
    )
    assert text_on_page(pages, 1, "10-2099-0000001 출원의 청구항 제1항은 쉽게 발명할 수 있습니다.")


def test_쪽을_넘은_표_칸은_시작_쪽에서_이어_붙여_찾는다():
    pages = _pages(
        "본문",
        "본문",
        tables={
            1: [[HEAD, ["1", "청구항 제1항 내지", "특허법 제29조제2항"]]],
            2: [[["", "제3항", ""]]],
        },
    )
    assert text_on_page(pages, 1, "청구항 제1항 내지 제3항")


def test_없는_글자_없는_쪽_빈_글자는_안_됨():
    assert not text_on_page(SPLIT, 1, "지어낸 문장")
    assert not text_on_page(SPLIT, 9, "습니다.")
    assert not text_on_page(SPLIT, None, "습니다.")
    assert not text_on_page(SPLIT, 1, "  ")
