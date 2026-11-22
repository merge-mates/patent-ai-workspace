"""올린 문서의 쪽 글자 읽기 (GET /documents/{id}, 이슈 #262).

화면 "참고 원문"이 통지서 쪽 글자를 보인다. 쪽 글자는 저장하지 않고 요청 때 원본 PDF에서 뽑는다
(F3·F4 입력 글자 texts_source와 같은 방식: 로컬 PDF라 빠르다).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from patent_ai.core.cases.store import CaseAppStore
from patent_ai.core.f1_oa_reader.pages import PdfReadError, extract_pages
from patent_ai.core.schemas.common import Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.document import PageText

logger = logging.getLogger(__name__)

ReadPages = Callable[[Path, str], PageText]


def read_document_pages(
    store: CaseAppStore, document_id: str, read_pages: ReadPages = extract_pages
) -> PageText | None:
    """문서 ID → 쪽 글자. 없는 문서면 None (API는 404).

    문서 줄은 있는데 원본을 못 읽으면(파일 없음·깨짐) 빈 쪽 + 확인되지 않음(lookup_failed).
    요청은 맞으니 오류로 올리지 않고 status로 알린다 (docs/api/README.md 1절).
    """
    path = store.get_document_path(document_id)
    if path is None:
        return None
    try:
        return read_pages(Path(path), document_id)
    except PdfReadError as e:
        logger.warning("document_pages: %s 원본을 못 읽음 (%s)", document_id, e)
        return PageText(
            document_id=document_id,
            pages=[],
            # checked는 confirmed일 때만 채우는 칸이라 이유는 로그에만 남긴다
            status=Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.LOOKUP_FAILED),
        )
