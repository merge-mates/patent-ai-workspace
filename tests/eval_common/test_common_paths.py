"""저장소 경로·실험 이름·커밋 해시 (eval/common/paths.py)."""

from pathlib import Path

import pytest

from eval.common.errors import EvalError
from eval.common.paths import REPO_ROOT, check_experiment_name, git_commit, is_git_ignored


def test_저장소_뿌리를_가리킨다():
    assert (REPO_ROOT / "pyproject.toml").is_file()
    assert (REPO_ROOT / "eval" / "common").is_dir()


def test_저장소_밖은_git_무시로_친다(tmp_path):
    assert is_git_ignored(tmp_path / "x")


def test_work_아래는_무시되고_docs_아래는_아니다():
    assert is_git_ignored(REPO_ROOT / "work" / "x")
    assert not is_git_ignored(REPO_ROOT / "docs" / "x")


@pytest.mark.parametrize("bad", ["", "../x", "a/b", "a\\b", ".."])
def test_실험_이름에_경로_조각이_있으면_막는다(bad):
    with pytest.raises(EvalError, match="경로 조각"):
        check_experiment_name(bad)


def test_보통_실험_이름은_통과():
    check_experiment_name("m1-i3-f1-baseline")


def test_커밋_해시는_글자다():
    c = git_commit()
    assert isinstance(c, str) and c
    assert c == "unknown" or len(c) == 40


def test_git이_없으면_unknown(monkeypatch):
    import eval.common.paths as paths

    monkeypatch.setattr(paths, "REPO_ROOT", Path("/nonexistent-repo-root"))
    assert paths.git_commit() == "unknown"
