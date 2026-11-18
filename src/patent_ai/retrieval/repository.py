"""조각 저장소 (design.md 5-1절). 테스트용 메모리 저장소.

core를 import하지 않는다. Postgres 저장소는 m2-i2에서 같은 Protocol로 더한다.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Protocol

from patent_ai.retrieval.schemas import Chunk, Corpus


class ChunkRepository(Protocol):
    """조각을 읽고 센다. 색인 판·문헌·기준일 거르기는 구현이 같게 한다."""

    def chunks(
        self,
        corpus: Corpus,
        index_version: str,
        doc_ids: list[str] | None = None,
        as_of: date | None = None,
    ) -> list[Chunk]: ...

    def has_index_version(self, corpus: Corpus, index_version: str) -> bool: ...

    def count_chunks(
        self, corpus: Corpus, index_version: str, doc_ids: list[str] | None = None
    ) -> int: ...

    def count_unverified_edition(
        self, corpus: Corpus, index_version: str, doc_ids: list[str] | None = None
    ) -> int: ...


def _check_doc_ids(doc_ids: list[str] | None) -> None:
    # None만 "전체"다. 빈 목록은 실수일 가능성이 커서 조용히 0건을 돌려주지 않고 막는다
    if doc_ids is not None and len(doc_ids) == 0:
        raise ValueError("doc_ids가 빈 목록이다. 전체는 None으로 표현한다")


def _in_force(chunk: Chunk, as_of: date) -> bool:
    """그 날짜에 시행 중인 판본인가. effective_from <= as_of <= effective_to (끝 없으면 현행)."""
    ed = chunk.edition
    if ed.status == "unverified":
        return False  # 판본을 모르면 기준일 검색에서 뺀다 (센 것은 count_unverified_edition)
    if ed.status == "not_applicable":
        return True  # 인용문헌은 판본이 없어 기준일로 거르지 않는다
    if ed.effective_from is None:
        return False  # confirmed인데 시작일이 없으면 그날 시행인지 알 수 없다
    if as_of < ed.effective_from:
        return False
    return ed.effective_to is None or as_of <= ed.effective_to


class InMemoryChunkRepository:
    def __init__(self, tables: dict[Corpus, list[Chunk]]):
        self._tables = tables

    @classmethod
    def from_jsonl(cls, corpus: Corpus, *paths: str | Path) -> InMemoryChunkRepository:
        """JSONL 줄마다 Chunk 하나. Chunk에 말뭉치 칸이 없어서 어느 표인지 인자로 받는다."""
        prefix = re.compile(rf"^{corpus}-idx-v[0-9]+$")
        rows: list[Chunk] = []
        seen: set[str] = set()
        for path in paths:
            for no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                chunk = Chunk.model_validate_json(line)
                # 말뭉치와 색인 판 앞말이 다르면 (law 표에 cite-idx-v1) 막는다
                if not prefix.match(chunk.index_version):
                    raise ValueError(
                        f"{path}:{no} 색인 판 {chunk.index_version!r}이 {corpus}와 안 맞는다"
                    )
                if chunk.chunk_id in seen:
                    raise ValueError(f"{path}:{no} chunk_id가 겹친다: {chunk.chunk_id}")
                seen.add(chunk.chunk_id)
                rows.append(chunk)
        return cls({corpus: rows})

    @classmethod
    def merge(cls, *repos: InMemoryChunkRepository) -> InMemoryChunkRepository:
        """말뭉치마다 만든 저장소를 하나로 합친다. 같은 말뭉치가 둘이면 이어 붙인다."""
        tables: dict[Corpus, list[Chunk]] = {}
        for repo in repos:
            for corpus, rows in repo._tables.items():
                tables.setdefault(corpus, []).extend(rows)
        for corpus, rows in tables.items():
            ids = [c.chunk_id for c in rows]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{corpus} 표에 chunk_id가 겹친다")
        return cls(tables)

    def _scope(self, corpus: Corpus, index_version: str, doc_ids: list[str] | None) -> list[Chunk]:
        _check_doc_ids(doc_ids)
        allowed = None if doc_ids is None else set(doc_ids)
        return [
            c
            for c in self._tables.get(corpus, [])
            if c.index_version == index_version and (allowed is None or c.doc_id in allowed)
        ]

    def chunks(
        self,
        corpus: Corpus,
        index_version: str,
        doc_ids: list[str] | None = None,
        as_of: date | None = None,
    ) -> list[Chunk]:
        rows = self._scope(corpus, index_version, doc_ids)
        if as_of is not None:
            rows = [c for c in rows if _in_force(c, as_of)]
        return rows

    def has_index_version(self, corpus: Corpus, index_version: str) -> bool:
        return any(c.index_version == index_version for c in self._tables.get(corpus, []))

    def count_chunks(
        self, corpus: Corpus, index_version: str, doc_ids: list[str] | None = None
    ) -> int:
        return len(self._scope(corpus, index_version, doc_ids))

    def count_unverified_edition(
        self, corpus: Corpus, index_version: str, doc_ids: list[str] | None = None
    ) -> int:
        rows = self._scope(corpus, index_version, doc_ids)
        return sum(1 for c in rows if c.edition.status == "unverified")
