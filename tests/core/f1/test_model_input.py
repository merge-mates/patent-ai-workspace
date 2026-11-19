"""모델에 넣는 통지서 글자 (이슈 #122 task-a). 표 글자는 지어낸 것.

raw: 지금처럼 `[쪽 N]` + 쪽 글자. tables_md: 각 쪽 글자 뒤에 그 쪽에서 시작하는 표
(쪽을 넘은 칸은 이어 붙인 것)를 `[쪽 N 표]` 아래 마크다운으로 덧붙인다.
"""

import pytest

from patent_ai.core.f1_oa_reader.model_input import model_input
from patent_ai.core.schemas.common import Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.document import Page, PageText

HEAD = ["순번", "거절이유가 있는 부분", "관련 법조항"]
OK = Status(value=StatusValue.CONFIRMED, checked="글자 있음")


def _pages(*pages: tuple[str, list]) -> PageText:
    return PageText(
        document_id="d_1",
        pages=[
            Page(page=i, text=text, status=OK, tables=tables)
            for i, (text, tables) in enumerate(pages, start=1)
        ],
        status=OK,
    )


def test_raw는_지금처럼_쪽_표시와_쪽_글자만():
    pages = _pages(
        ("첫 쪽 글자", [[HEAD, ["1", "청구항 제1항", "특허법 제29조제2항"]]]), ("둘째", [])
    )
    assert model_input(pages, "raw") == "[쪽 1]\n첫 쪽 글자\n\n[쪽 2]\n둘째"


def test_표가_없으면_tables_md도_raw와_같다():
    pages = _pages(("가", []), ("나", []))
    assert model_input(pages, "tables_md") == model_input(pages, "raw")


def test_표는_그_쪽_글자_뒤에_마크다운으로_붙는다():
    pages = _pages(("본문", [[HEAD, ["1", "청구항 제6항,\n제7항", "특허법 제42조제4항제2호"]]]))
    assert model_input(pages, "tables_md") == (
        "[쪽 1]\n본문\n\n[쪽 1 표]\n"
        "| 순번 | 거절이유가 있는 부분 | 관련 법조항 |\n"
        "|---|---|---|\n"
        "| 1 | 청구항 제6항, 제7항 | 특허법 제42조제4항제2호 |"  # 칸 안 줄바꿈은 공백
    )


def test_쪽을_넘은_칸은_이어_붙여_시작_쪽_표에_한_칸으로():
    pages = _pages(
        ("1쪽", [[HEAD, ["3", "청구항 제1항 내지 제4항, 제8항 내지", "특허법 제29조제2항"]]]),
        ("2쪽", [[["", "제10항", ""]]]),
    )
    out = model_input(pages, "tables_md")
    assert "| 3 | 청구항 제1항 내지 제4항, 제8항 내지 제10항 | 특허법 제29조제2항 |" in out
    # 붙인 조각은 2쪽 표로 다시 나오지 않는다 (2쪽에는 표가 남지 않음)
    assert "[쪽 2 표]" not in out
    assert out.index("[쪽 1 표]") < out.index("[쪽 2]")


def test_줄_사이에서_넘은_표는_다음_쪽_첫_표가_그_쪽에_따로():
    pages = _pages(
        ("1쪽", [[HEAD, ["1", "청구항 제1항", "특허법 제29조제2항"]]]),
        ("2쪽", [[["2", "청구항 제2항", "특허법 제29조제1항"]]]),
    )
    out = model_input(pages, "tables_md")
    two = out[out.index("[쪽 2]") :]
    assert "[쪽 2 표]\n| 2 | 청구항 제2항 | 특허법 제29조제1항 |\n|---|---|---|" in two


def test_빈_쪽은_쪽_표시만():
    empty = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.BODY_MISSING)
    pages = PageText(
        document_id="d_1",
        pages=[Page(page=1, text="", status=empty), Page(page=2, text="나", status=OK)],
        status=OK,
    )
    assert model_input(pages, "tables_md") == "[쪽 1]\n\n\n[쪽 2]\n나"


def test_빈_칸과_칸_수가_다른_줄과_칸_안_세로줄():
    pages = _pages(("본문", [[["a", "b", "c"], ["", "x|y"]]]))
    assert model_input(pages, "tables_md").endswith("| a | b | c |\n|---|---|---|\n|  | x\\|y |  |")


def test_모르는_방식이면_조용히_넘어가지_않고_오류():
    with pytest.raises(ValueError, match="model_input"):
        model_input(_pages(("가", [])), "markdown")  # type: ignore[arg-type]
