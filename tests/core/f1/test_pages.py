"""쪽 글자 뽑기 테스트. PDF는 테스트 안에서 지어낸 글자로 만든다 (실제 통지서 아님)."""

import logging
from pathlib import Path

import pdfplumber
import pytest
from reportlab.pdfgen import canvas

from patent_ai.core.f1_oa_reader.pages import PdfReadError, extract_pages
from patent_ai.core.schemas.common import StatusValue, UnverifiedReason
from patent_ai.core.schemas.document import Page, PageText


def _make_pdf(path: Path, texts: list[str | None]) -> Path:
    """texts의 None은 글자 없이 사각형만 그린 쪽 (스캔본 흉내)."""
    c = canvas.Canvas(str(path))
    for t in texts:
        if t is None:
            c.rect(100, 100, 200, 200, fill=1)
        else:
            c.drawString(72, 720, t)
        c.showPage()
    c.save()
    return path


def test_두_쪽_PDF는_쪽_번호와_글자가_나온다(tmp_path):
    pdf = _make_pdf(
        tmp_path / "a.pdf",
        ["Application No. 10-2099-0000001", "Claim 1 is rejected."],
    )
    result = extract_pages(pdf, "doc-1")
    assert isinstance(result, PageText)
    assert result.document_id == "doc-1"
    assert [p.page for p in result.pages] == [1, 2]
    assert "10-2099-0000001" in result.pages[0].text
    assert "Claim 1 is rejected." in result.pages[1].text
    assert all(isinstance(p, Page) for p in result.pages)
    assert all(p.status.value == StatusValue.CONFIRMED for p in result.pages)
    assert result.status.value == StatusValue.CONFIRMED
    # 쪽 checked에 그 쪽 글자 수가 남는다
    n = len(result.pages[1].text)
    assert result.pages[1].status.checked == f"pdfplumber 글자 층에서 추출, {n}자"


def test_PDF가_아닌_파일은_PdfReadError(tmp_path):
    f = tmp_path / "x.pdf"
    f.write_text("이건 PDF가 아님")
    with pytest.raises(PdfReadError):
        extract_pages(f, "doc-1")


def test_깨진_PDF는_PdfReadError(tmp_path):
    good = _make_pdf(tmp_path / "a.pdf", ["hello"])
    broken = tmp_path / "b.pdf"
    broken.write_bytes(good.read_bytes()[:60])  # 앞부분만 남김
    with pytest.raises(PdfReadError) as e:
        extract_pages(broken, "doc-1")
    assert "hello" not in str(e.value)  # 파일 안 글자는 오류 메시지에 안 넣는다


def test_파일이_없으면_PdfReadError(tmp_path):
    with pytest.raises(PdfReadError, match="없"):
        extract_pages(tmp_path / "none.pdf", "doc-1")


def test_scanned_모든_쪽이_그림뿐이면_문서도_unverified(tmp_path):
    result = extract_pages(_make_pdf(tmp_path / "s.pdf", [None]), "doc-1")
    assert result.pages[0].text == ""
    assert result.pages[0].status.value == StatusValue.UNVERIFIED
    assert result.pages[0].status.reason == UnverifiedReason.BODY_MISSING
    assert result.status.value == StatusValue.UNVERIFIED
    assert result.status.reason == UnverifiedReason.BODY_MISSING


def test_blank_일부_쪽만_없으면_문서는_confirmed(tmp_path):
    pdf = _make_pdf(tmp_path / "m.pdf", ["Page one text", None, "Page three text"])
    result = extract_pages(pdf, "doc-1")
    assert [p.status.value for p in result.pages] == [
        StatusValue.CONFIRMED,
        StatusValue.UNVERIFIED,
        StatusValue.CONFIRMED,
    ]
    assert result.pages[1].status.reason == UnverifiedReason.BODY_MISSING
    assert result.status.value == StatusValue.CONFIRMED
    assert result.status.checked == "글자 있는 쪽 2/3"


def test_blank_공백뿐인_쪽도_글자_없음(tmp_path):
    result = extract_pages(_make_pdf(tmp_path / "w.pdf", ["   "]), "doc-1")
    assert result.pages[0].status.value == StatusValue.UNVERIFIED


def test_blank_0쪽_PDF는_unverified와_경고(tmp_path, monkeypatch, caplog):
    # reportlab은 0쪽 PDF를 못 만들어 pdfplumber.open 결과를 흉내 낸다
    class _Empty:
        pages: list = []

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    f = tmp_path / "z.pdf"
    f.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(pdfplumber, "open", lambda _p: _Empty())
    with caplog.at_level(logging.WARNING):
        result = extract_pages(f, "doc-1")
    assert result.pages == []
    assert result.status.value == StatusValue.UNVERIFIED
    assert result.status.reason == UnverifiedReason.BODY_MISSING
    assert any("0쪽" in r.message for r in caplog.records)


# ---- 쪽마다 표 (task-8: 쪽을 넘어간 거절이유 표 칸) ----
def _make_table_pdf(path: Path, tables_by_page: list[list[list[str]]]) -> Path:
    """쪽마다 칸선 있는 표 하나. 한글은 reportlab 내장 CID 글꼴 (글꼴 파일 없이 CI에서도 돈다)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import PageBreak, SimpleDocTemplate, Table, TableStyle

    pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
    style = TableStyle(
        [
            ("FONT", (0, 0), (-1, -1), "HYSMyeongJo-Medium", 9),
            ("GRID", (0, 0), (-1, -1), 0.5, "black"),
        ]
    )
    story: list = []
    for i, rows in enumerate(tables_by_page):
        if i:
            story.append(PageBreak())
        story.append(Table(rows, style=style))
    SimpleDocTemplate(str(path), pagesize=A4).build(story)
    return path


def test_표가_있는_쪽은_tables에_행과_칸이_나온다(tmp_path):
    pdf = _make_table_pdf(
        tmp_path / "t.pdf",
        [
            [
                ["순번", "거절이유가 있는 부분", "관련 법조항"],
                ["1", "청구항 제1항 내지 제4항, 제8항 내지", "특허법 제29조제2항"],
            ],
            [["", "제10항", ""]],
        ],
    )
    result = extract_pages(pdf, "doc-1")
    assert result.pages[0].tables == [
        [
            ["순번", "거절이유가 있는 부분", "관련 법조항"],
            ["1", "청구항 제1항 내지 제4항, 제8항 내지", "특허법 제29조제2항"],
        ]
    ]
    assert result.pages[1].tables == [[["", "제10항", ""]]]  # 빈 칸은 "" (None 아님)


def test_표가_없는_쪽은_tables가_빈_목록이고_예전_JSON도_읽힌다(tmp_path):
    result = extract_pages(_make_pdf(tmp_path / "a.pdf", ["hello"]), "doc-1")
    assert result.pages[0].tables == []
    # tables 칸이 없는 예전 모양(#17 응답)도 그대로 읽힌다 (기본값 빈 목록)
    ok = {"value": "confirmed", "reason": None, "checked": "x", "searched_scope": None}
    old = {"document_id": "d", "pages": [{"page": 1, "text": "a", "status": ok}], "status": ok}
    assert PageText.model_validate(old).pages[0].tables == []


def test_표_찾기만_실패하면_그_쪽_표는_빈_목록이고_글자는_그대로(tmp_path, monkeypatch, caplog):
    pdf = _make_pdf(tmp_path / "a.pdf", ["hello"])

    def boom(self, *a, **k):
        raise ValueError("표 찾기 실패")

    monkeypatch.setattr(pdfplumber.page.Page, "extract_tables", boom)
    with caplog.at_level(logging.WARNING):
        result = extract_pages(pdf, "doc-1")
    assert result.pages[0].text == "hello"
    assert result.pages[0].tables == []
    assert any("표를 못 읽음" in r.message for r in caplog.records)
