"""조각 표 두 개(law_chunks, cite_chunks)의 ORM·마이그레이션을 DB 없이 본다.

오프라인 SQL(`alembic upgrade head --sql`)과 ORM 칸 목록을 비교한다.
실제 CHECK 거부는 db 테스트(tests/test_retrieval_db.py)에서 본다.
"""

import re
import subprocess
import sys

import pytest

from patent_ai.db.models import CiteChunk, LawChunk

# design.md 5-1 표의 칸 (순서 무관)
EXPECTED_COLUMNS = {
    "chunk_id",
    "index_version",
    "doc_id",
    "chunk_kind",
    "loc_kind",
    "loc_start",
    "loc_end",
    "loc_figures",
    "loc_claims",
    "loc_label",
    "edition_status",
    "edition_effective_from",
    "edition_effective_to",
    "edition_label",
    "text",
    "embedding",
    "created_at",
}


@pytest.fixture(scope="module")
def offline_sql() -> str:
    res = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    return res.stdout


def _create_table(sql: str, table: str) -> str:
    m = re.search(rf"CREATE TABLE {table} \((.*?)\n\);", sql, re.S)
    assert m, f"{table} 표를 만드는 SQL이 없다"
    return m.group(1)


# 법령 표에만 있는 칸 (#24, design 5-1)
LAW_ONLY_COLUMNS = {"source_kind", "decided_on", "speaker", "attrs"}


def test_두_표의_ORM_칸이_설계_표와_맞고_새_칸_넷은_법령_표에만_있다():
    law = {c.name for c in LawChunk.__table__.columns}
    cite = {c.name for c in CiteChunk.__table__.columns}
    assert cite == EXPECTED_COLUMNS
    assert law == EXPECTED_COLUMNS | LAW_ONLY_COLUMNS
    assert LawChunk.__tablename__ == "law_chunks"
    assert CiteChunk.__tablename__ == "cite_chunks"


def test_오프라인_SQL에_표_둘과_확장과_길이없는_vector가_있다(offline_sql):
    assert "CREATE EXTENSION IF NOT EXISTS vector" in offline_sql
    for table in ("law_chunks", "cite_chunks"):
        body = _create_table(offline_sql, table)
        assert re.search(r"embedding VECTOR\s*,", body + ",") or re.search(
            r"embedding VECTOR\s*(,|$)", body, re.M
        )
        assert "VECTOR(" not in body
    # 확장은 표보다 먼저
    assert offline_sql.index("CREATE EXTENSION") < offline_sql.index("CREATE TABLE law_chunks")


def test_edition_status는_NOT_NULL이다(offline_sql):
    for table in ("law_chunks", "cite_chunks"):
        body = _create_table(offline_sql, table)
        assert re.search(r"edition_status TEXT NOT NULL", body)


def test_오프라인_SQL에_두_CHECK_문구가_있다(offline_sql):
    law = _create_table(offline_sql, "law_chunks")
    cite = _create_table(offline_sql, "cite_chunks")
    assert "'^law-idx-v[0-9]+$'" in law
    assert "'^cite-idx-v[0-9]+$'" in cite
    for body in (law, cite):
        assert "edition_status IN ('confirmed', 'unverified', 'not_applicable')" in body


def test_인덱스가_있다(offline_sql):
    # 표마다 따로 본다 (한 표 인덱스만 있어도 통과하지 않게)
    assert "ON law_chunks (index_version, doc_id)" in offline_sql
    assert "ON cite_chunks (index_version, doc_id)" in offline_sql
    assert "ON law_chunks (index_version, edition_effective_from)" in offline_sql


def test_법령_표_새_칸_NOT_NULL과_CHECK(offline_sql):
    cite = _create_table(offline_sql, "cite_chunks")
    # 새 칸은 ALTER로 더해지고 source_kind는 채운 뒤 NOT NULL로 바뀐다 (기존 행 보호)
    assert "ALTER TABLE law_chunks ADD COLUMN source_kind TEXT" in offline_sql
    assert "UPDATE law_chunks SET source_kind = 'statute'" in offline_sql
    assert "ALTER TABLE law_chunks ALTER COLUMN source_kind SET NOT NULL" in offline_sql
    assert "ck_law_chunks_source_kind CHECK (source_kind IN ('statute', 'guideline'" in offline_sql
    assert "ck_law_chunks_speaker CHECK (speaker IN ('court', 'party', 'unknown')" in offline_sql
    assert "source_kind" not in cite  # 인용문헌 표는 그대로
