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
