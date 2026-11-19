"""쪽 글자 추출 인터페이스 (지어낸 작은 PDF 하나로 한 번만)."""

from pathlib import Path

import pytest

from patent_ai.retrieval.cite_index import PageText, PdfplumberExtractor

TINY = Path(__file__).parent.parent / "fixtures" / "cite_search" / "tiny.pdf"


def test_tiny_pdf_쪽수와_첫_줄():
    pages = PdfplumberExtractor().extract(TINY)
    assert [p.page for p in pages] == [1, 2]
    assert pages[0].lines[0] == "Tiny first line"
    assert pages[1].lines == ["Page two body"]


def test_PageText_모양():
    assert PageText(page=3, lines=["a"]).lines == ["a"]


def test_없는_파일은_오류(tmp_path):
    with pytest.raises(FileNotFoundError):
        PdfplumberExtractor().extract(tmp_path / "none.pdf")
