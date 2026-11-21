"""git 제외 검사 하나 (PR #163 리뷰: cite_index·score·eval paths 세 곳을 하나로)."""

from patent_ai.git_paths import REPO_ROOT, is_git_ignored


def test_git이_무시하는_경로는_통과():
    assert is_git_ignored(REPO_ROOT / "work" / "x.jsonl")
    assert is_git_ignored(REPO_ROOT / "data" / "processed" / "x.jsonl")


def test_추적되는_경로는_거절():
    assert not is_git_ignored(REPO_ROOT / "docs" / "x.md")


def test_저장소_밖은_기본으로_거절(tmp_path):
    assert not is_git_ignored(tmp_path / "x.jsonl")


def test_저장소_밖_허용을_켜면_통과(tmp_path):
    assert is_git_ignored(tmp_path / "x.jsonl", outside_ok=True)
    # 허용을 켜도 저장소 안 추적 경로는 거절
    assert not is_git_ignored(REPO_ROOT / "docs" / "x.md", outside_ok=True)


def test_상대_경로는_지금_폴더_기준(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)
    assert is_git_ignored("work/x.jsonl")
    assert not is_git_ignored("docs/x.md")
