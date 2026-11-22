"""실제 Postgres에 마이그레이션이 끝까지 올라가는지 (로컬 make test-db, CI는 서비스 컨테이너)."""

import subprocess
import sys

import pytest


@pytest.mark.db
def test_alembic_upgrade_head_on_real_db():
    res = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert res.returncode == 0, res.stderr


@pytest.mark.db
def test_default_user_is_exactly_one_after_upgrade():
    # 빈 DB(CI)에 마이그레이션을 올린 뒤 기본 사용자 한 명 (이슈 #55 합격 기준 2)
    from sqlalchemy import create_engine, text

    from patent_ai.settings import get_settings

    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    engine = create_engine(get_settings().database_url)
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id FROM users")).scalars().all()
    engine.dispose()

    assert rows == ["u_default"]


def _alembic(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "alembic", *args], check=True)


@pytest.mark.db
def test_law_chunks_새_칸_upgrade는_옛_행을_statute로_채우고_downgrade로_되돌아간다():
    # 이슈 #24 24a: 옛 행(v1·v2) 보호. 앞 revision에서 행을 넣고 올린다
    from sqlalchemy import create_engine, inspect, text

    from patent_ai.settings import get_settings

    prev, rev = "d9e4b1c7a352", "c7e2a5d9f103"
    # CI는 테스트 전에 head까지 올려 두므로 앞 revision으로 내려가서 시작한다
    _alembic("upgrade", "head")
    _alembic("downgrade", prev)
    engine = create_engine(get_settings().database_url)
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM law_chunks WHERE chunk_id = 'law-idx-v2:mig:1'"))
            conn.execute(
                text(
                    "INSERT INTO law_chunks (chunk_id, index_version, doc_id, chunk_kind, loc_kind,"
                    " loc_label, edition_status, text) VALUES ('law-idx-v2:mig:1', 'law-idx-v2',"
                    " 'mig', 'article', 'article', '제1조', 'unverified', '가짜')"
                )
            )
        _alembic("upgrade", rev)
        with engine.connect() as conn:
            kinds = (
                conn.execute(
                    text("SELECT source_kind FROM law_chunks WHERE chunk_id = 'law-idx-v2:mig:1'")
                )
                .scalars()
                .all()
            )
        assert kinds == ["statute"]
        cols = {c["name"]: c for c in inspect(engine).get_columns("law_chunks")}
        assert cols["source_kind"]["nullable"] is False
        assert {"decided_on", "speaker", "attrs"} <= set(cols)

        _alembic("downgrade", prev)
        cols = {c["name"] for c in inspect(engine).get_columns("law_chunks")}
        assert not ({"source_kind", "decided_on", "speaker", "attrs"} & cols)
    finally:
        _alembic("upgrade", "head")
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM law_chunks WHERE chunk_id = 'law-idx-v2:mig:1'"))
        engine.dispose()
