"""저장소 경로, git 무시 검사, 실험 이름 검사, 커밋 해시."""

import subprocess
from pathlib import Path

from eval.common.errors import EvalError

# 저장소 뿌리 (eval/common/paths.py 기준 두 단계 위)
REPO_ROOT = Path(__file__).resolve().parents[2]


def is_git_ignored(path: Path) -> bool:
    """저장소 밖이면 통과. 안이면 git check-ignore로 무시되는 경로여야 통과."""
    p = Path(path).resolve()
    try:
        p.relative_to(REPO_ROOT)
    except ValueError:
        return True
    r = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", "--", str(p)],
        capture_output=True,
    )
    return r.returncode == 0


def check_experiment_name(experiment: str) -> None:
    # 실험 이름이 경로 조각이면 experiments/·work/ 폴더 밖으로 나갈 수 있다
    if not experiment or "/" in experiment or "\\" in experiment or ".." in experiment:
        raise EvalError("실험 이름에 경로 조각(/, .. 등)이 있다")


def git_commit() -> str:
    """지금 커밋 해시. git을 못 쓰면 unknown (scores.json에 남김)."""
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return r.stdout.strip() or "unknown"
    except subprocess.CalledProcessError, OSError:
        return "unknown"
