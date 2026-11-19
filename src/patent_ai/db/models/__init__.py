"""DB 모델 모음. 여기서 import해야 Alembic이 표를 본다 (migrations/env.py)."""

from patent_ai.db.models.cases import OA, Case, CaseEvent, Claim, ClaimVersion, Document, User
from patent_ai.db.models.chunks import ChunkColumns, CiteChunk, LawChunk

__all__ = [
    "OA",
    "Case",
    "CaseEvent",
    "ChunkColumns",
    "CiteChunk",
    "Claim",
    "ClaimVersion",
    "Document",
    "LawChunk",
    "User",
]
