"""인용문헌 원문 전체 (GET /citations/{doc_id}): 색인 조각을 문헌 순서대로.

화면 오른쪽 판이 근거 문단만이 아니라 인용문헌 전체를 스크롤해 보이고 근거 문단을 강조하려고 쓴다.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends

from patent_ai.api.errors import AppError
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
