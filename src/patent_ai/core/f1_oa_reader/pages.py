"""통지서 PDF에서 쪽마다 글자를 뽑는다. PDF 도구(pdfplumber)는 이 함수 뒤에만 둔다."""

from pathlib import Path

import pdfplumber

from patent_ai.core.schemas.common import Status, StatusValue
from patent_ai.core.schemas.document import Page, PageText


class PdfReadError(Exception):
    """PDF를 읽지 못함 (없음·PDF 아님·깨짐). 빈 결과로 넘기지 않고 이유와 함께 낸다."""


def extract_pages(pdf_path: Path, document_id: str) -> PageText:
    """PDF를 열어 쪽 번호(1부터)별 글자를 돌려준다."""
    if not pdf_path.is_file():
        raise PdfReadError(f"파일이 없음: {pdf_path.name}")
    pages: list[Page] = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for number, pdf_page in enumerate(pdf.pages, start=1):
                text = pdf_page.extract_text() or ""
                # 글자 판정(없는 쪽 unverified)은 task-2에서. 지금은 모두 confirmed
                pages.append(
                    Page(
                        page=number,
                        text=text,
                        status=Status(
                            value=StatusValue.CONFIRMED,
                            checked="pdfplumber 글자 층에서 추출",
                        ),
                    )
                )
    except PdfReadError:
        raise
    except Exception as e:  # pdfplumber/pdfminer는 여러 종류 오류를 냄: 한 오류로 모은다
        raise PdfReadError(f"PDF를 읽지 못함: {pdf_path.name} ({type(e).__name__})") from e
    return PageText(
        document_id=document_id,
        pages=pages,
        status=Status(value=StatusValue.CONFIRMED, checked=f"{len(pages)}쪽 모두 글자 추출"),
    )
