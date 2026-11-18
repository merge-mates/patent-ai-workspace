"""DB 모델 모음. 여기서 import해야 Alembic이 표를 본다 (migrations/env.py)."""

from patent_ai.db.models.chunks import ChunkColumns, CiteChunk, LawChunk

__all__ = ["ChunkColumns", "CiteChunk", "LawChunk"]
