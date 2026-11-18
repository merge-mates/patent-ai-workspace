"""통지서 PDF에서 쪽마다 글자를 뽑는다. PDF 도구(pdfplumber)는 이 함수 뒤에만 둔다."""

import logging
from pathlib import Path

import pdfplumber

from patent_ai.core.schemas.common import Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.document import Page, PageText

logger = logging.getLogger(__name__)


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
                text = (pdf_page.extract_text() or "").strip()
                if text:
                    status = Status(
                        value=StatusValue.CONFIRMED,
                        checked=f"pdfplumber 글자 층에서 추출, {len(text)}자",
                    )
                else:  # 글자 층이 없는 쪽(스캔·그림뿐): 실패 대신 확인되지 않음
                    status = Status(
                        value=StatusValue.UNVERIFIED, reason=UnverifiedReason.BODY_MISSING
                    )
                pages.append(Page(page=number, text=text, status=status))
                pdf_page.close()  # 쪽 캐시를 풀어 메모리를 아낀다
    except Exception as e:  # pdfplumber/pdfminer는 여러 종류 오류를 냄: 한 오류로 모은다
        raise PdfReadError(f"PDF를 읽지 못함: {pdf_path.name} ({type(e).__name__})") from e
    # 문서 status: 글자 있는 쪽이 하나도 없을 때만 unverified (0쪽도 포함)
    with_text = sum(1 for p in pages if p.status.value == StatusValue.CONFIRMED)
    if with_text == 0:
        if not pages:
            logger.warning("extract_pages: 0쪽 PDF: %s", pdf_path.name)
        doc_status = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.BODY_MISSING)
    else:
        doc_status = Status(
            value=StatusValue.CONFIRMED, checked=f"글자 있는 쪽 {with_text}/{len(pages)}"
        )
    return PageText(document_id=document_id, pages=pages, status=doc_status)
