"""report 정답 폴더(data/goldsets/report/)를 Claude 도구로 여는 것을 막는 훅 테스트.

훅에는 도구 입력(JSON)만 넘긴다. 실제 파일은 열지 않는다 (가짜 저장소 경로 글자만 쓴다).
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "block_report_goldset.py"
REPO = "/fake/repo"  # 없는 가짜 저장소. 훅은 경로 글자만 보고 파일을 열지 않는다


def run_hook_raw(stdin: str) -> int:
    """훅을 부르고 종료 코드를 돌려준다. 2 = 막음, 0 = 통과."""
    env = {**os.environ, "CLAUDE_PROJECT_DIR": REPO}
    done = subprocess.run(
        ["python3", str(HOOK)], input=stdin, capture_output=True, text=True, env=env
    )
    return done.returncode


def run_hook(tool_name: str, tool_input: dict, cwd: str = REPO) -> int:
    payload = {"tool_name": tool_name, "tool_input": tool_input, "cwd": cwd}
    return run_hook_raw(json.dumps(payload))


FAKE = "data/goldsets/report/__fake__.json"

BLOCKED_BASH = [
    # 경로를 직접 여는 명령
    f"cat {FAKE}",
    f"head -n 5 {FAKE}",
    f"less {FAKE}",
    f"tail {FAKE}",
    "rg 출원 data/goldsets/report/",
    "grep -n 거절 data/goldsets/report/f1/case1.json",
    f"python3 -c \"print(open('{FAKE}').read())\"",
    f"uv run python -c \"import json; json.load(open('{FAKE}'))\"",
    f"cat /Users/someone/repo/{FAKE}",
    f"cat ../wt/x/{FAKE}",
    f"cat {REPO}/data/Goldsets/Report/x.json",  # 대소문자 (macOS 디스크)
    "cd data/goldsets && cat report/f1/case1.json",
    "cd data && cat goldsets/report/x.json",
    "cd data/goldsets/report; ls",
    "ls data/goldsets",
    # .. 로 tune을 거쳐 돌아가기 (리뷰 #143)
    "cat data/goldsets/tune/../report/x.json",
    # 와일드카드 (리뷰 #143: gold 글자가 없어도)
    "cat data/goldsets/*/f1/case1.json",
    "cat data/goldsets/r*/x.json",
    "cat data/*/report/x.json",
    "cat data/g*/report/x.json",
    "cat data/*/*/*.json",
    "python3 -c \"import glob; print(glob.glob('data/gold*/*'))\"",
    # 인터프리터로 넘기는 heredoc 안의 경로
    f"python3 - <<'EOF'\nprint(open('{FAKE}').read())\nEOF",
    # data 폴더 전체를 훑는 명령
    "grep -r 거절 data",
    "grep -R 거절 data/",
    "grep -rn 거절 .",
    "grep -r 거절",  # 경로 없음 = 지금 폴더 (리뷰 #143)
    "grep -r 거절 *",
    "grep -r 거절 data/*",
    "rg 거절 data",  # 대상을 직접 주면 .gitignore와 상관없이 읽음 (리뷰 #143)
    "rg -l 거절 data/",
    "rg --no-ignore 거절",
    "rg --no-ignore-vcs 거절",
    "rg -uu 거절 .",
    "find data -name '*.json' -exec cat {} +",
    "find . -name '*.json' -exec cat {} +",  # 리뷰 #143
    "find . -name '*.json' | xargs cat",
    "tar czf x.tgz data",
    "tar czf x.tgz .",
    "cp -r data /tmp/x",
    "cp -r . /tmp/x",
    "zip -r x.zip .",
    "ls -R data",
]


@pytest.mark.parametrize("command", BLOCKED_BASH)
def test_bash_report_access_blocked(command: str) -> None:
    assert run_hook("Bash", {"command": command}) == 2


ALLOWED_BASH = [
    "uv run pytest",
    "uv run ruff check",
    "cat data/goldsets/tune/f1/case1.json",
    "ls data/goldsets/tune",
    "cat data/goldsets/VERSION",
    "uv run python eval/run_eval.py --config experiments/m1-report-f1/config.yaml",
    "rg goldset eval/",
    "grep -rn report src/",
    "git log --oneline -5",
    "ls data/raw",
    "ls data/raw/*",
    "ls *",
    "find . -name '*.json'",
    "rg 거절",  # 지금 폴더를 돌 때는 .gitignore(/data)를 따름
    "rg 거절 .",
    # 검색어·메시지 자리의 goldsets 글자 (리뷰 #143)
    "rg goldsets eval/",
    "rg -n 'data/goldsets' src/",
    "git grep goldsets",
    "git log --grep goldsets",
    'git commit -m "docs: data/goldsets/ 설명 고치기"',
    "git commit -q -F - <<'EOF'\ndocs: data/goldsets/report 설명\nEOF",
    "echo data/goldsets/report",
]


@pytest.mark.parametrize("command", ALLOWED_BASH)
def test_bash_normal_commands_pass(command: str) -> None:
    assert run_hook("Bash", {"command": command}) == 0


@pytest.mark.parametrize(
    ("tool", "tool_input"),
    [
        ("Read", {"file_path": f"/Users/someone/repo/{FAKE}"}),
        ("Read", {"file_path": f"{REPO}/data/goldsets/tune/../report/x.json"}),
        ("Grep", {"pattern": "거절", "path": "data/goldsets/report"}),
        ("Grep", {"pattern": "거절", "path": "data/goldsets"}),
        ("Grep", {"pattern": "거절", "path": "data"}),  # 리뷰 #143
        ("Grep", {"pattern": "거절", "path": f"{REPO}/data"}),
        ("Glob", {"pattern": "data/goldsets/report/**/*.json"}),
        ("Glob", {"pattern": "**/*.json", "path": "data/goldsets"}),
        ("Glob", {"pattern": "**/*.json", "path": "data"}),  # 리뷰 #143
        ("Glob", {"pattern": "data/**/*.json"}),
    ],
)
def test_file_tools_report_blocked(tool: str, tool_input: dict) -> None:
    assert run_hook(tool, tool_input) == 2


@pytest.mark.parametrize(
    ("tool", "tool_input"),
    [
        ("Read", {"file_path": "data/goldsets/tune/f1/case1.json"}),
        ("Grep", {"pattern": "report", "path": "src"}),
        ("Grep", {"pattern": "goldsets/report"}),  # 검색어 자리는 경로가 아님
        ("Glob", {"pattern": "src/**/*.py"}),
        ("Glob", {"pattern": "**/*.py"}),
    ],
)
def test_file_tools_normal_pass(tool: str, tool_input: dict) -> None:
    assert run_hook(tool, tool_input) == 0


@pytest.mark.parametrize(
    "stdin",
    [
        "not json",
        '{"tool_name":"Bash","tool_input":"cat x"}',  # 모양이 다름 (리뷰 #143)
        "[]",
    ],
)
def test_broken_input_blocks(stdin: str) -> None:
    """입력을 못 읽거나 훅 안에서 예외가 나면 조용히 통과시키지 않고 막는다."""
    assert run_hook_raw(stdin) == 2
