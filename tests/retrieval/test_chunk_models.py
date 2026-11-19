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


def test_두_표의_ORM_칸이_같고_설계_표와_맞다():
    law = {c.name for c in LawChunk.__table__.columns}
    cite = {c.name for c in CiteChunk.__table__.columns}
    assert law == cite == EXPECTED_COLUMNS
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
