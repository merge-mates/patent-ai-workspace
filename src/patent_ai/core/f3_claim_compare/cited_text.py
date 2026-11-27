"""인용문헌 원문 전체 보기: 색인에 넣어 둔 인용문헌 조각을 문헌 순서대로 잇는다.

인용문헌 PDF는 로컬에 있고, 그 본문은 이미 색인(cite)에 문단 단위로 들어 있다
(F3 대비가 쓰는 것과 같은 판).
화면 오른쪽 판에서 근거 문단만이 아니라 문헌 전체를 스크롤해 보고, 근거 문단을 강조하려고 쓴다.
순서: 요약 → 청구항(번호순) → 본문 문단(식별번호순) → 도면 설명(도면 번호순).
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict

from patent_ai.retrieval.repository import ChunkRepository
from patent_ai.retrieval.schemas import Chunk

logger = logging.getLogger(__name__)

# 조각 종류별 문헌 안 순서 (모르는 종류는 맨 뒤)
_KIND_ORDER = {"abstract": 0, "claim": 1, "body": 2, "figure_desc": 3}


class CitedPart(BaseModel):
    """문헌 조각 하나 (화면에서 한 문단)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    kind: str  # abstract | claim | body | figure_desc
    label: str  # 원문 표기 그대로 ([0023], 청구항 1, 도 1, 요약)
    text: str


class CitedDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: str
    index_version: str
    parts: list[CitedPart]


def _order(c: Chunk) -> tuple:
    loc = c.location
    number = (
        (loc.claims[0] if loc.claims else 0)
        if c.chunk_kind == "claim"
        else (loc.figures[0] if loc.figures else 0)
        if c.chunk_kind == "figure_desc"
        else (loc.start or 0)
    )
    # 긴 조각을 나눈 것(-part2 …)은 chunk_id 순서로 이어진다
    return (_KIND_ORDER.get(c.chunk_kind, 9), number, c.chunk_id)


def cited_document(repo: ChunkRepository, index_version: str, doc_id: str) -> CitedDocument | None:
    """그 인용문헌의 조각 전체를 문헌 순서로. 색인에 조각이 없으면 None."""
    chunks = repo.chunks("cite", index_version, [doc_id])
    if not chunks:
        logger.warning("cited_text: 색인 %s에 문헌 %s 조각이 없음", index_version, doc_id)
        return None
    parts = [
        CitedPart(chunk_id=c.chunk_id, kind=c.chunk_kind, label=c.location.label, text=c.text)
        for c in sorted(chunks, key=_order)
    ]
    return CitedDocument(doc_id=doc_id, index_version=index_version, parts=parts)


def cite_index_version() -> str:
    """앱 F3가 대비에 쓰는 인용문헌 색인 판 (config/f3.yaml search.index_version)."""
    from patent_ai.core.f3_claim_compare.config import load_f3_settings

    return load_f3_settings().search.index_version


def open_cite_repo() -> ChunkRepository:
    """색인 DB 저장소 (api가 retrieval을 바로 부르지 않게 core에서 연다)."""
    from patent_ai.retrieval.repository import PostgresChunkRepository

    return PostgresChunkRepository.from_url()
