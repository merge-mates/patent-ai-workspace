"""PDF에서 쪽마다 줄 목록을 뽑는 인터페이스와 pdfplumber 구현."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pdfplumber


@dataclass
class PageText:
    page: int  # 1부터 시작하는 PDF 쪽 순서
    lines: list[str]


class PageExtractor(Protocol):
    def extract(self, pdf_path: Path) -> list[PageText]: ...


class PdfplumberExtractor:
    """pdfplumber 구현. 글자가 없는 쪽은 빈 lines로 남긴다 (쪽 번호가 밀리지 않게)."""

    def extract(self, pdf_path: Path) -> list[PageText]:
        path = Path(pdf_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        pages: list[PageText] = []
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                pages.append(PageText(page=i, lines=text.splitlines()))
        return pages
