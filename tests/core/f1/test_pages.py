"""쪽 글자 뽑기 테스트. PDF는 테스트 안에서 지어낸 글자로 만든다 (실제 통지서 아님)."""

from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from patent_ai.core.f1_oa_reader.pages import PdfReadError, extract_pages
from patent_ai.core.schemas.common import StatusValue
from patent_ai.core.schemas.document import Page, PageText


def _make_pdf(path: Path, texts: list[str]) -> Path:
    c = canvas.Canvas(str(path))
    for t in texts:
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


def test_PDF가_아닌_파일은_PdfReadError(tmp_path):
    f = tmp_path / "x.pdf"
    f.write_text("이건 PDF가 아님")
    with pytest.raises(PdfReadError):
        extract_pages(f, "doc-1")


def test_깨진_PDF는_PdfReadError(tmp_path):
    good = _make_pdf(tmp_path / "a.pdf", ["hello"])
    broken = tmp_path / "b.pdf"
    broken.write_bytes(good.read_bytes()[:60])  # 앞부분만 남김
    with pytest.raises(PdfReadError):
        extract_pages(broken, "doc-1")


def test_파일이_없으면_PdfReadError(tmp_path):
    with pytest.raises(PdfReadError, match="없"):
        extract_pages(tmp_path / "none.pdf", "doc-1")
