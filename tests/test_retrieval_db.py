"""PostgresChunkRepository: 메모리 저장소와 같은 거르기를 하는지 (make db 뒤 make test-db)."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from patent_ai.db.models.chunks import CiteChunk, LawChunk
from patent_ai.retrieval.repository import (
    InMemoryChunkRepository,
    PostgresChunkRepository,
    chunk_to_row,
    row_to_chunk,
)
from patent_ai.settings import get_settings

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).parent / "fixtures" / "retrieval"


@pytest.fixture
def session():
    """바깥 트랜잭션 안에서 세션을 열고 끝에 되돌린다. 몇 번 돌려도 chunk_id가 안 겹친다."""
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


@pytest.fixture
def both(session):
    """같은 fixture 조각을 메모리 저장소와 DB 두 표에 넣는다."""
    mem = InMemoryChunkRepository.merge(
        InMemoryChunkRepository.from_jsonl("cite", FIXTURES / "chunks_cite.jsonl"),
        InMemoryChunkRepository.from_jsonl("law", FIXTURES / "chunks_law.jsonl"),
    )
    for corpus, rows in mem._tables.items():
        session.add_all([chunk_to_row(corpus, c) for c in rows])
    session.flush()
    return mem, PostgresChunkRepository(session)


def _ids(chunks):
    return {c.chunk_id for c in chunks}


def test_변환은_왕복해도_같다(both):
    mem, _ = both
    for corpus, rows in mem._tables.items():
        for c in rows:
            back = row_to_chunk(chunk_to_row(corpus, c))
            assert back == c


@pytest.mark.parametrize("corpus", ["law", "cite"])
def test_같은_질의에_두_저장소의_조각이_같다(both, corpus):
    mem, pg = both
    rows = mem._tables[corpus]
    assert rows  # fixture가 비면 비교가 의미 없다
    version = rows[0].index_version
    doc_ids = sorted({c.doc_id for c in rows})
    # 기준일: 구판·신판 경계 앞뒤, 아주 이른 날, 아주 늦은 날
    dates = [None, date(1990, 1, 1), date(2015, 1, 1), date(2019, 12, 31), date(2020, 1, 1)]
    dates += [date(2099, 1, 1)]
    for as_of in dates:
        for docs in (None, doc_ids[:1], ["없는공보"]):
            assert _ids(pg.chunks(corpus, version, docs, as_of)) == _ids(
                mem.chunks(corpus, version, docs, as_of)
            )
    for docs in (None, doc_ids[:1], ["없는공보"]):
        assert pg.count_chunks(corpus, version, docs) == mem.count_chunks(corpus, version, docs)
        assert pg.count_unverified_edition(corpus, version, docs) == (
            mem.count_unverified_edition(corpus, version, docs)
        )


def test_법령은_기준일에_그날_판본만_남고_인용문헌은_안_거른다(both):
    mem, pg = both
    law_v = mem._tables["law"][0].index_version
    cite_v = mem._tables["cite"][0].index_version
    # 판본을 모르는 조각이 fixture에 있어야 이 비교가 의미 있다
    assert pg.count_unverified_edition("law", law_v) > 0
    assert len(pg.chunks("law", law_v, as_of=date(2017, 1, 1))) < pg.count_chunks("law", law_v)
    assert _ids(pg.chunks("cite", cite_v, as_of=date(1990, 1, 1))) == _ids(
        pg.chunks("cite", cite_v)
    )
    assert pg.count_unverified_edition("cite", cite_v) == 0


def test_없는_색인_판은_false이고_말뭉치_표만_본다(both):
    mem, pg = both
    assert pg.has_index_version("law", "law-idx-v999") is False
    assert pg.has_index_version("law", mem._tables["law"][0].index_version) is True
    # cite 색인 판 이름을 law 표에서 찾으면 없다
    assert pg.has_index_version("law", mem._tables["cite"][0].index_version) is False


def test_doc_ids가_빈_목록이면_오류(both):
    _, pg = both
    for call in (pg.chunks, pg.count_chunks, pg.count_unverified_edition):
        with pytest.raises(ValueError):
            call("law", "law-idx-v1", [])


def test_법령_표에_cite_색인_판을_넣으면_CHECK_위반(session):
    chunk = InMemoryChunkRepository.from_jsonl("law", FIXTURES / "chunks_law.jsonl")._tables["law"][
        0
    ]
    row = chunk_to_row("law", chunk)
    row.index_version = "cite-idx-v1"
    session.add(row)
    with pytest.raises(IntegrityError, match="ck_law_chunks_index_version"):
        session.flush()


def test_edition_status_없이_넣으면_NOT_NULL_위반(session):
    chunk = InMemoryChunkRepository.from_jsonl("cite", FIXTURES / "chunks_cite.jsonl")._tables[
        "cite"
    ][0]
    row = chunk_to_row("cite", chunk)
    row.edition_status = None
    session.add(row)
    with pytest.raises(IntegrityError, match="edition_status"):
        session.flush()


def test_표_클래스는_말뭉치로_고른다(session):
    chunk = InMemoryChunkRepository.from_jsonl("cite", FIXTURES / "chunks_cite.jsonl")._tables[
        "cite"
    ][0]
    assert isinstance(chunk_to_row("cite", chunk), CiteChunk)
    assert isinstance(chunk_to_row("law", chunk), LawChunk)
