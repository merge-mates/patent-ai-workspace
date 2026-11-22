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


def test_offline_sql_adds_stop_reason_and_output_truncated_to_agent_steps():
    # 이슈 #172: 모델 호출 기록에 stop_reason 칸, outcome에 output_truncated
    sql = _offline_sql()
    assert re.search(r"ALTER TABLE agent_steps ADD COLUMN stop_reason TEXT", sql)
    last_check = re.findall(r"ADD CONSTRAINT ck_agent_steps_outcome CHECK \(([^;]*)\);", sql)[-1]
    assert "'output_truncated'" in last_check
    assert "'invalid_output'" in last_check


# --- 이슈 #57 T5: 건너뛴 단계 ---


def _values(check_sql: str) -> set[str]:
    """CHECK 글자에서 따옴표 안 값만 모은다."""
    return set(re.findall(r"'([^']+)'", check_sql))


def test_offline_sql_agent_steps_outcome_check_matches_model():
    # 마이그레이션(마지막 CHECK)과 모델의 값 집합이 같아야 한다.
    # #181(output_truncated)과 합칠 때 한쪽에만 값을 넣는 실수를 잡는다.
    from patent_ai.db.models import AgentStep

    checks = re.findall(r"ADD CONSTRAINT ck_agent_steps_outcome CHECK \(([^;]*)\)", _offline_sql())
    assert checks, "ck_agent_steps_outcome을 다시 만드는 줄이 없다"
    model = next(
        c
        for c in AgentStep.__table__.constraints
        if getattr(c, "name", None) == "ck_agent_steps_outcome"
    )
    assert _values(checks[-1]) == _values(str(model.sqltext))
    assert "skipped" in _values(checks[-1])


def test_skipped_마이그레이션의_옛_CHECK는_앞_마이그레이션의_새_CHECK와_같다():
    # downgrade가 앞 판(#181 c4a8f1e63b27)과 같은 CHECK를 다시 만들어야 한다 (#187 리뷰)
    import importlib.util
    from pathlib import Path

    versions = Path(__file__).resolve().parents[1] / "src/patent_ai/db/migrations/versions"

    def load(name: str):
        spec = importlib.util.spec_from_file_location(name, versions / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    prev = load("20261121_c4a8f1e63b27_agent_steps_stop_reason")
    skipped = load("20261121_e5d3a7b92c18_agent_steps_outcome_skipped")
    assert skipped.down_revision == prev.revision
    assert _values(skipped._OLD) == _values(prev._NEW)
    assert _values(skipped._NEW) == _values(prev._NEW) | {"skipped"}


# --- 이슈 #70 방향 선택 기록·실행 종류 ---


def test_offline_sql_adds_direction_selections_and_runs_kind():
    sql = _offline_sql()
    assert "CREATE TABLE direction_selections" in sql
    assert re.search(r"ALTER TABLE runs ADD COLUMN kind TEXT DEFAULT 'full' NOT NULL", sql)
    assert "ck_runs_kind" in sql
