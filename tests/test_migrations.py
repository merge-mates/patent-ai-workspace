"""마이그레이션 설정이 깨지지 않았는지 DB 없이 본다 (alembic 오프라인 모드: SQL만 만든다)."""

import re
import subprocess
import sys


def test_alembic_upgrade_head_offline_runs_without_db():
    res = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert res.returncode == 0, res.stderr


# --- 이슈 #55 첫 마이그레이션 ---

M1_TABLES = {
    "users",
    "cases",
    "case_events",
    "documents",
    "claim_versions",
    "claims",
    "oas",
    "rejections",
    "cited_references",
    "rejection_claims",
    "rejection_citations",
    "oa_results",
    "case_materials",
    "runs",
    "agent_steps",
    "result_inputs",
    "api_cache",
}
RETRIEVAL_CHUNKS_REVISION = "57c073821f45"


def _script():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(Config("alembic.ini"))


def _offline_sql():
    res = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout


def test_migrations_form_one_line_after_retrieval_chunks():
    # head가 둘이면 나중에 머지하는 쪽이 down_revision을 고친다 (db/CLAUDE.md)
    script = _script()
    heads = script.get_heads()
    assert len(heads) == 1
    m1 = next(r for r in script.walk_revisions() if r.down_revision == RETRIEVAL_CHUNKS_REVISION)
    assert m1.revision is not None


def test_offline_sql_creates_every_m1_table():
    created = set(re.findall(r"CREATE TABLE (\w+)", _offline_sql()))
    assert M1_TABLES <= created


def test_every_db_model_table_is_in_a_migration():
    # DB 모델에 표를 더하고 마이그레이션을 빠뜨리지 않게
    from patent_ai.db import models  # noqa: F401
    from patent_ai.db.base import Base

    created = set(re.findall(r"CREATE TABLE (\w+)", _offline_sql()))
    assert set(Base.metadata.tables) <= created


def test_offline_sql_inserts_one_default_user():
    inserts = re.findall(r"INSERT INTO users\b.*", _offline_sql())
    assert len(inserts) == 1
    assert "u_default" in inserts[0]


# --- 이슈 #57 T5: 건너뛴 단계 ---


def test_offline_sql_agent_steps_outcome_check_allows_skipped():
    # 오프라인 SQL에서 새 CHECK가 skipped를 허용하는지 (옛 CHECK는 지워진다)
    sql = _offline_sql()
    checks = re.findall(r"ADD CONSTRAINT ck_agent_steps_outcome CHECK \(([^;]*)\)", sql)
    assert checks, "ck_agent_steps_outcome을 다시 만드는 줄이 없다"
    assert "'skipped'" in checks[-1]
    assert "'waiting'" in checks[-1]
