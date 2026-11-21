"""저장소 경로, git 무시 검사, 실험 이름 검사, 커밋 해시."""

import subprocess
from pathlib import Path

from eval.common.errors import EvalError
from patent_ai.git_paths import REPO_ROOT
from patent_ai.git_paths import is_git_ignored as _is_git_ignored

# 저장소 뿌리와 git 제외 검사는 patent_ai/git_paths.py 하나를 쓴다 (앱 색인 스크립트와 같은 검사)
__all__ = ["REPO_ROOT", "check_experiment_name", "git_commit", "is_git_ignored"]


def is_git_ignored(path: Path) -> bool:
    """저장소 밖이면 통과 (채점기 테스트가 tmp에 씀).

    안이면 git check-ignore로 무시되는 경로여야 통과.
    """
    return _is_git_ignored(path, outside_ok=True)


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
