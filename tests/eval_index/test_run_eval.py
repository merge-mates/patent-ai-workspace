"""채점 명령 하나 (eval/run_eval.py): 설정의 feature 칸으로 기능 채점기를 고른다."""

import subprocess
import sys
from pathlib import Path

import pytest

import eval.run_eval as run_eval

REPO_ROOT = Path(__file__).resolve().parents[2]


def _cfg(tmp_path, text: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_feature로_채점기를_고르고_인자를_그대로_넘긴다(tmp_path, monkeypatch):
    seen = {}

    def fake(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setitem(run_eval.SCORERS, "retrieval", fake)
    cfg = _cfg(tmp_path, "experiment: x\nfeature: retrieval\n")
    assert run_eval.main(["--config", str(cfg), "--chunks", "c.jsonl"]) == 0
    assert seen["argv"] == ["--config", str(cfg), "--chunks", "c.jsonl"]


def test_채점기가_실패하면_그_종료_코드를_돌려준다(tmp_path, monkeypatch):
    monkeypatch.setitem(run_eval.SCORERS, "retrieval", lambda argv: 1)
    cfg = _cfg(tmp_path, "feature: retrieval\n")
    assert run_eval.main(["--config", str(cfg)]) == 1


def test_검색_채점기가_연결돼_있다():
    from eval.retrieval.score import main as retrieval_main

    assert run_eval.SCORERS["retrieval"] is retrieval_main


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("experiment: x\n", "feature"),
        ("feature: nope\n", "nope"),
        ("feature: [1, 2]\n", "feature"),
        ("", "비었거나"),
    ],
)
def test_feature가_없거나_모르면_실패(tmp_path, capsys, text, why):
    assert run_eval.main(["--config", str(_cfg(tmp_path, text))]) == 1
    assert why in capsys.readouterr().err


def test_설정_파일이_없으면_실패(tmp_path, capsys):
    assert run_eval.main(["--config", str(tmp_path / "nope.yaml")]) == 1
    assert "없다" in capsys.readouterr().err


def test_파일로_직접_실행해도_import된다(tmp_path):
    # /experiment 스킬은 `python eval/run_eval.py`로 부른다 (모듈 실행 아님)
    cfg = _cfg(tmp_path, "feature: nope\n")
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "eval" / "run_eval.py"), "--config", str(cfg)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert r.returncode == 1
    assert "nope" in r.stderr
    assert "ModuleNotFoundError" not in r.stderr
