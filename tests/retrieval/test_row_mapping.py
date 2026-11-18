"""칸 매핑이 두 곳(db.index_dump, retrieval.repository)에 있어 어긋나지 않는지 본다."""

from pathlib import Path

import pytest

from patent_ai.db.index_dump import fixture_rows
from patent_ai.retrieval.repository import InMemoryChunkRepository, chunk_to_row

FIXTURES = Path(__file__).parent.parent / "fixtures" / "retrieval"
# created_at 같은 DB 기본값 칸은 빼고 비교한다
SKIP = {"created_at", "updated_at"}


def _values(row):
    return {c.key: getattr(row, c.key) for c in row.__table__.columns if c.key not in SKIP}


@pytest.mark.parametrize("corpus", ["cite", "law"])
def test_fixture_rows와_chunk_to_row의_칸_값이_같다(corpus):
    path = FIXTURES / f"chunks_{corpus}.jsonl"
    a = fixture_rows(corpus, path.read_text(encoding="utf-8"))
    repo = InMemoryChunkRepository.from_jsonl(corpus, path)
    b = [chunk_to_row(corpus, c) for c in repo._tables[corpus]]
    assert a and len(a) == len(b)
    assert [_values(r) for r in a] == [_values(r) for r in b]
