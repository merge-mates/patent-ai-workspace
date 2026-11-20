"""색인 쓰기: 두 번 써도 줄 수가 같고 PostgresChunkRepository가 읽는다 (make test-db)."""

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from patent_ai.db.models.chunks import CiteChunk
from patent_ai.retrieval.cite_index.__main__ import write_index
from patent_ai.retrieval.repository import PostgresChunkRepository
from patent_ai.retrieval.schemas import Chunk, Edition, Location
from patent_ai.settings import get_settings

pytestmark = pytest.mark.db

IV = "cite-idx-v1"


@pytest.fixture
def session():
    engine = create_engine(get_settings().database_url)
    conn = engine.connect()
    outer = conn.begin()
    sess = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield sess
    finally:
        sess.close()
        outer.rollback()
        conn.close()
        engine.dispose()


def _chunk(key: str, doc="KRTEST1A") -> Chunk:
    return Chunk(
        chunk_id=f"{IV}:{doc}:{key}",
        index_version=IV,
        doc_id=doc,
        chunk_kind="body",
        location=Location(kind="page", start=1, end=1, label="1쪽"),
        edition=Edition(status="not_applicable"),
        text="지어낸 글자",
    )


def _count(session) -> int:
    return session.scalar(
        select(func.count()).select_from(CiteChunk).where(CiteChunk.index_version == IV)
    )


def test_두_번_써도_줄_수가_같다(session):
    chunks = [_chunk("pg1"), _chunk("pg2")]
    write_index(session, chunks)
    first = _count(session)
    write_index(session, chunks)
    assert _count(session) == first == 2


def test_이전_줄은_지우고_새_줄로_바꾼다(session):
    write_index(session, [_chunk("pg1"), _chunk("pg2")])
    write_index(session, [_chunk("pg3")])
    assert _count(session) == 1


def test_쓴_줄을_저장소가_읽는다(session):
    write_index(session, [_chunk("pg1")])
    repo = PostgresChunkRepository(session)
    assert repo.has_index_version("cite", IV)
    got = repo.chunks("cite", IV, doc_ids=["KRTEST1A"])
    assert [c.chunk_id for c in got] == [f"{IV}:KRTEST1A:pg1"]
