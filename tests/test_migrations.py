"""마이그레이션 설정이 깨지지 않았는지 DB 없이 본다 (alembic 오프라인 모드: SQL만 만든다)."""

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
