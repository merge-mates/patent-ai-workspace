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
