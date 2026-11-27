"""인용문헌 원문 전체 (GET /citations/{doc_id}): 색인 조각을 문헌 순서대로.

화면 오른쪽 판이 근거 문단만이 아니라 인용문헌 전체를 스크롤해 보이고 근거 문단을 강조하려고 쓴다.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from patent_ai.api.errors import AppError
from patent_ai.core.cases.local_citations import configured_root, local_citation_file
from patent_ai.core.f3_claim_compare.cited_text import (
    CitedDocument,
    cite_index_version,
    cited_document,
    open_cite_repo,
)

router = APIRouter()


def get_cite_repo() -> Iterator:
    repo = open_cite_repo()
    try:
        yield repo
    finally:
        close = getattr(repo, "close", None)
        if close:
            close()


def get_cite_index_version() -> str:
    return cite_index_version()


@router.get("/citations/{doc_id}", response_model=CitedDocument)
def get_cited_document(
    doc_id: str,
    repo: Annotated[object, Depends(get_cite_repo)],
    index_version: Annotated[str, Depends(get_cite_index_version)],
) -> CitedDocument:
    doc = cited_document(repo, index_version, doc_id)  # type: ignore[arg-type]
    if doc is None:
        raise AppError(404, "citation_not_found", "색인에 없는 인용문헌입니다")
    return doc


def get_cite_root():
    """로컬 인용문헌 폴더 (config/cite_search.yaml raw_root). 없으면 None."""
    return configured_root()


@router.get("/citations/{doc_id}/file", response_class=FileResponse)
def get_cited_file(
    doc_id: str,
    application_number: str,
    root: Annotated[object, Depends(get_cite_root)],
) -> FileResponse:
    # 인용문헌 원본 PDF (원문 판이 PDF로 보인다). 그 사건(출원번호) 폴더의 그 번호 파일만
    file = local_citation_file(application_number, doc_id, root) if root else None  # type: ignore[arg-type]
    if file is None:
        raise AppError(404, "citation_file_not_found", "인용문헌 원본 PDF를 찾을 수 없습니다")
    return FileResponse(file, media_type="application/pdf")
