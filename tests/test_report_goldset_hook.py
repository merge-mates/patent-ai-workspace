"""report 정답 폴더(data/goldsets/report/)를 Claude 도구로 여는 것을 막는 훅 테스트.

훅에는 도구 입력(JSON)만 넘긴다. 실제 파일은 열지 않는다 (가짜 경로 글자만 쓴다).
"""

import json
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "block_report_goldset.py"


def run_hook(tool_name: str, tool_input: dict) -> int:
    """훅을 부르고 종료 코드를 돌려준다. 2 = 막음, 0 = 통과."""
    payload = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
    done = subprocess.run(["python3", str(HOOK)], input=payload, capture_output=True, text=True)
    return done.returncode


FAKE = "data/goldsets/report/__fake__.json"

BLOCKED_BASH = [
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
    "cd data/goldsets && cat report/f1/case1.json",
    "cd data/goldsets/report; ls",
    "ls data/goldsets",
    "cat data/goldsets/*/f1/case1.json",
    "cat data/goldsets/r*/x.json",
    "python3 -c \"import glob; print(glob.glob('data/gold*/*'))\"",
    "grep -r 거절 data",
    "grep -R 거절 data/",
    "grep -rn 거절 .",
    "rg --no-ignore 거절",
    "rg -uu 거절 .",
    "find data -name '*.json' -exec cat {} +",
    "tar czf x.tgz data",
    "cp -r data /tmp/x",
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
]


@pytest.mark.parametrize("command", ALLOWED_BASH)
def test_bash_normal_commands_pass(command: str) -> None:
    assert run_hook("Bash", {"command": command}) == 0


@pytest.mark.parametrize(
    ("tool", "tool_input"),
    [
        ("Read", {"file_path": f"/Users/someone/repo/{FAKE}"}),
        ("Grep", {"pattern": "거절", "path": "data/goldsets/report"}),
        ("Grep", {"pattern": "거절", "path": "data/goldsets"}),
        ("Glob", {"pattern": "data/goldsets/report/**/*.json"}),
        ("Glob", {"pattern": "**/*.json", "path": "data/goldsets"}),
    ],
)
def test_file_tools_report_blocked(tool: str, tool_input: dict) -> None:
    assert run_hook(tool, tool_input) == 2


@pytest.mark.parametrize(
    ("tool", "tool_input"),
    [
        ("Read", {"file_path": "data/goldsets/tune/f1/case1.json"}),
        ("Grep", {"pattern": "report", "path": "src"}),
        ("Glob", {"pattern": "src/**/*.py"}),
    ],
)
def test_file_tools_normal_pass(tool: str, tool_input: dict) -> None:
    assert run_hook(tool, tool_input) == 0


def test_broken_input_blocks() -> None:
    """입력을 못 읽으면 조용히 통과시키지 않고 막는다."""
    done = subprocess.run(["python3", str(HOOK)], input="not json", capture_output=True, text=True)
    assert done.returncode == 2
