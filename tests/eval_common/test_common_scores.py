"""scores.json 쓰기 (eval/common/scores.py). 필수 칸은 experiments/_template/scores.schema.json."""

import json

import pytest

from eval.common.errors import EvalError
from eval.common.scores import write_scores


def _scores(**over):
    s = {
        "experiment": "m1-i3-x-y",
        "commit": "abc",
        "goldset": "tune",
        "goldset_version": 1,
        "n": 3,
        "metrics": {"hit@5": 0.5},
        "failures": {"excluded_clarity": 1},
        "cost": {"usd": 0, "seconds": 0.1},
    }
    s.update(over)
    return s


def test_폴더를_만들고_scores_json을_쓴다(tmp_path):
    out = write_scores(tmp_path / "a" / "b", _scores(extra_key="kept"))
    assert out == tmp_path / "a" / "b" / "scores.json"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["n"] == 3
    assert data["extra_key"] == "kept"  # 기능마다 더 넣는 칸은 막지 않는다
    assert out.read_text(encoding="utf-8").endswith("}\n")


def test_한글을_그대로_쓴다(tmp_path):
    out = write_scores(tmp_path, _scores(metric_name="심사관 지정 위치 회수율"))
    assert "심사관" in out.read_text(encoding="utf-8")


@pytest.mark.parametrize("key", ["experiment", "commit", "goldset_version", "n", "cost"])
def test_필수_칸이_빠지면_실패하고_파일을_안_쓴다(tmp_path, key):
    s = _scores()
    del s[key]
    with pytest.raises(EvalError, match=key):
        write_scores(tmp_path, s)
    assert not (tmp_path / "scores.json").exists()


def test_n이_0이면_실패(tmp_path):
    with pytest.raises(EvalError, match="n"):
        write_scores(tmp_path, _scores(n=0))


@pytest.mark.parametrize(
    ("key", "bad"),
    [
        ("goldset_version", "tune-f1-v0"),
        ("n", 1.5),
        ("metrics", {"hit@5": "high"}),
        ("failures", {"x": 0.5}),
        ("metrics", {"hit@5": None}),
        ("goldset_version", True),
    ],
)
def test_칸_꼴이_틀리면_실패(tmp_path, key, bad):
    with pytest.raises(EvalError, match=key):
        write_scores(tmp_path, _scores(**{key: bad}))
