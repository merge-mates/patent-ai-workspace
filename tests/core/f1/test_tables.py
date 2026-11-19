"""쪽을 넘어간 표 칸 이어 붙이기와 거절이유 표 줄 읽기 (task-8). 표 글자는 지어낸 것."""

from patent_ai.core.f1_oa_reader.tables import RejectionRow, merged_tables, rejection_rows
from patent_ai.core.schemas.common import Status, StatusValue
from patent_ai.core.schemas.document import Page, PageText

HEAD = ["순번", "거절이유가 있는 부분", "관련 법조항"]


def _pages(*tables_by_page: list) -> PageText:
    ok = Status(value=StatusValue.CONFIRMED, checked="글자 있음")
    return PageText(
        document_id="d_1",
        pages=[
            Page(page=i, text="본문", status=ok, tables=t)
            for i, t in enumerate(tables_by_page, start=1)
        ],
        status=ok,
    )


def test_평소_한_쪽_안의_표는_그대로_줄이_된다():
    pages = _pages(
        [
            [
                HEAD,
                ["1", "청구항 제6항, 제7항", "특허법 제42조제4항제2호"],
                ["2", "청구항 제1항", "특허법 제29조제2항"],
            ]
        ]
    )
    assert rejection_rows(pages) == [
        RejectionRow(no=1, page=1, part="청구항 제6항, 제7항", article="특허법 제42조제4항제2호"),
        RejectionRow(no=2, page=1, part="청구항 제1항", article="특허법 제29조제2항"),
    ]


def test_잘린_칸은_다음_쪽_첫_줄_순번이_비면_앞_줄_같은_칸에_붙고_시작_쪽이다():
    pages = _pages(
        [[HEAD, ["3", "청구항 제1항 내지 제4항, 제8항 내지", "특허법 제29조제2항"]]],
        [[["", "제10항", ""]], [["다른 표", "x"]]],
    )
    assert rejection_rows(pages) == [
        RejectionRow(
            no=3,
            page=1,
            part="청구항 제1항 내지 제4항, 제8항 내지 제10항",
            article="특허법 제29조제2항",
        )
    ]
    # 붙인 줄은 다음 쪽 표에서 빠지고, 그 쪽의 다른 표는 그대로
    merged = merged_tables(pages)
    assert [(t.page, t.rows) for t in merged] == [
        (1, [HEAD, ["3", "청구항 제1항 내지 제4항, 제8항 내지 제10항", "특허법 제29조제2항"]]),
        (2, [["다른 표", "x"]]),
    ]
    assert rejection_rows(pages)[0].may_be_cut is False  # 조각을 붙였으니 잘린 줄 아님


def test_줄_사이에서_끊기면_다음_쪽_첫_표의_이어지는_순번도_줄이_된다():
    pages = _pages(
        [[HEAD, ["1", "청구항 제1항", "특허법 제29조제2항"]]],
        [[["2", "청구항 제2항", "특허법 제42조제4항제2호"]]],
    )
    assert [(r.no, r.page, r.part) for r in rejection_rows(pages)] == [
        (1, 1, "청구항 제1항"),
        (2, 2, "청구항 제2항"),
    ]


def test_앞_쪽에_표가_없으면_붙이지_않는다():
    pages = _pages([], [[["", "제10항", ""]]])
    assert [(t.page, t.rows) for t in merged_tables(pages)] == [(2, [["", "제10항", ""]])]
    assert rejection_rows(pages) == []


def test_머리_줄이_없으면_거절이유_줄은_없다():
    pages = _pages([[["순번", "인용발명", "비고"], ["1", "D1", ""]]])
    assert rejection_rows(pages) == []


def test_머리_줄_글자_사이_공백이_달라도_찾는다():
    head = ["순 번", "거절이유가 있는\n부분", "관련법조항"]
    pages = _pages([[head, ["1", "청구항 제1항", "특허법 제29조제2항"]]])
    assert [r.no for r in rejection_rows(pages)] == [1]


def test_줄_사이에서_끊긴_앞_줄은_잘린_줄이_아니다():
    pages = _pages(
        [[HEAD, ["1", "청구항 제1항", "특허법 제29조제2항"]]],
        [[["2", "청구항 제2항", "특허법 제42조제4항제2호"]], [["다른 표", "x", "y"]]],
    )
    assert [r.may_be_cut for r in rejection_rows(pages)] == [False, False]


def test_쪽_끝_줄인데_다음_쪽_조각을_못_찾으면_잘렸을_수_있음():
    # 칸이 "…제8항" | ", 제10항"처럼 잘렸는데 다음 쪽 조각이 표로 안 잡힌 경우 (리뷰에서 찾음)
    pages = _pages([[HEAD, ["1", "청구항 제1항 내지 제4항, 제8항", "특허법 제29조제2항"]]], [])
    assert rejection_rows(pages)[0].may_be_cut is True


def test_마지막_쪽의_마지막_줄은_잘린_줄이_아니다():
    pages = _pages([[HEAD, ["1", "청구항 제1항", "특허법 제29조제2항"]]])
    assert rejection_rows(pages)[0].may_be_cut is False


def test_목록_이음말_없이는_붙이지_않는다():
    # 앞 칸 끝도 조각 앞머리도 이음말이 아님: 잘린 칸이 아니라 다른 표 (붙이면 "제1항 제5항" → [15])
    pages = _pages(
        [[HEAD, ["1", "청구항 제1항", "특허법 제29조제2항"]]],
        [[["", "제5항", ""]]],
    )
    assert rejection_rows(pages)[0].part == "청구항 제1항"
    assert [t.page for t in merged_tables(pages)] == [1, 2]


def test_조각_앞머리에_이음말이_있으면_붙인다():
    pages = _pages(
        [[HEAD, ["1", "청구항 제1항 내지 제4항, 제8항", "특허법 제29조제2항"]]],
        [[["", ", 제10항", ""]]],
    )
    assert rejection_rows(pages)[0].part == "청구항 제1항 내지 제4항, 제8항 , 제10항"


def test_앞_쪽_마지막_표가_거절이유_표가_아니면_붙이지_않는다():
    pages = _pages(
        [[HEAD, ["1", "청구항 제1항", "특허법 제29조제2항"]], [["인용발명", "D1 내지"]]],
        [[["", "제5항"]]],
    )
    assert [t.page for t in merged_tables(pages)] == [1, 1, 2]
