"""DB 모델 모음. 여기서 import해야 Alembic이 표를 본다 (migrations/env.py)."""

from patent_ai.db.models.cases import OA, Case, CaseEvent, Claim, ClaimVersion, Document, User
from patent_ai.db.models.chunks import ChunkColumns, CiteChunk, LawChunk
from patent_ai.db.models.results import (
    CaseMaterialsRow,
    CitedReference,
    OAResultRow,
    Rejection,
    RejectionCitation,
    RejectionClaim,
    ResultInput,
    StepResultRow,
)
from patent_ai.db.models.runs import AgentStep, ApiCache, Run

__all__ = [
    "OA",
    "AgentStep",
    "ApiCache",
    "Case",
    "CaseEvent",
    "CaseMaterialsRow",
    "ChunkColumns",
    "CiteChunk",
    "CitedReference",
    "Claim",
    "ClaimVersion",
    "Document",
    "LawChunk",
    "OAResultRow",
    "Rejection",
    "RejectionCitation",
    "RejectionClaim",
    "ResultInput",
    "Run",
    "StepResultRow",
    "User",
]
