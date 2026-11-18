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
