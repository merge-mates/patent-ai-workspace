"""실험 점수 표 만들기 (eval/make_index.py). 가짜 실험 폴더는 tmp에 만든다."""

import json
import logging
from pathlib import Path

import pytest

from eval.common.errors import EvalError
from eval.make_index import build_index, main

REPO_ROOT = Path(__file__).resolve().parents[2]
HEAD = (
    "<!-- eval/make_index.py가 만든다. 손으로 고치지 않는다. -->\n"
    "# 실험 점수 표\n"
    "| 실험 | 기능 | 바꾼 것 | 주 지표 | 기준선 대비 | 비용 | 카드 |\n"
    "|---|---|---|---|---|---|---|\n"
)


def _card(
    name: str,
    baseline: str,
    *,
    feature="F1",
    changed="settings.model: a → b",
    primary="field_accuracy",
    drop: str | None = None,
) -> str:
    fields = {
        "실험": name,
        "기능": feature,
        "담당": "재아",
        "날짜": "2099-01-01",
        "기준선": f"experiments/{baseline}/",
        "평가 세트": "tune v1",
        "바꾼 것": changed,
        "주 지표": primary,
    }
    if drop:
        del fields[drop]
    head = "\n".join(f"{k}: {v}" for k, v in fields.items())
    return f"---\n{head}\n---\n# {name}\n\n**가설**: …\n"


def _exp(root: Path, name: str, baseline: str, metric: float | None, usd=0.12, **card_kw):
    d = root / name
    d.mkdir(parents=True)
    (d / "card.md").write_text(_card(name, baseline, **card_kw), encoding="utf-8")
    if metric is not None:
        scores = {"metrics": {"field_accuracy": metric}, "cost": {"usd": usd}, "n": 10}
        (d / "scores.json").write_text(json.dumps(scores), encoding="utf-8")
    return d


def _with_template(tmp_path) -> Path:
    root = tmp_path / "experiments"
    (root / "_template").mkdir(parents=True)
    (root / "_template" / "card.md").write_text(_card("<틀>", "<틀>"), encoding="utf-8")
    return root


def test_실험이_0개면_머리만_쓰고_지금_index와_같다(tmp_path, caplog):
    root = _with_template(tmp_path)
    with caplog.at_level(logging.WARNING):
        text = build_index(root)
    assert text == HEAD
    assert text == (REPO_ROOT / "experiments" / "index.md").read_text(encoding="utf-8")
    assert "0개" in caplog.text


def test_실험_둘이면_두_줄이고_기준선_대비_차이가_맞다(tmp_path):
    root = _with_template(tmp_path)
    _exp(root, "m1-i2-f1-baseline", "m1-i2-f1-baseline", 0.8, usd=0.1)
    _exp(root, "m1-i3-f1-model", "m1-i2-f1-baseline", 0.812, usd=0.25)
    lines = build_index(root).splitlines()[4:]
    assert lines == [
        "| m1-i2-f1-baseline | F1 | settings.model: a → b | field_accuracy 0.800 | 기준선 "
        "| $0.10 | [card](m1-i2-f1-baseline/card.md) |",
        "| m1-i3-f1-model | F1 | settings.model: a → b | field_accuracy 0.812 | +0.012 "
        "| $0.25 | [card](m1-i3-f1-model/card.md) |",
    ]


def test_점수가_내려가면_음수로_적는다(tmp_path):
    root = _with_template(tmp_path)
    _exp(root, "a-base", "a-base", 0.8)
    _exp(root, "b-worse", "a-base", 0.75)
    assert "| -0.050 |" in build_index(root)


def test_두_번_만들어도_같은_글자다(tmp_path):
    root = _with_template(tmp_path)
    _exp(root, "b-exp", "a-base", 0.7)
    _exp(root, "a-base", "a-base", 0.6)
    assert build_index(root) == build_index(root)
    # 이름 순서
    body = build_index(root).splitlines()[4:]
    assert body[0].startswith("| a-base ") and body[1].startswith("| b-exp ")


def test_scores가_없는_실험은_점수_없음_줄과_경고(tmp_path, caplog):
    root = _with_template(tmp_path)
    _exp(root, "a-base", "a-base", None)
    with caplog.at_level(logging.WARNING):
        text = build_index(root)
    assert (
        "| a-base | F1 | settings.model: a → b | 점수 없음 | - | - | [card](a-base/card.md) |"
        in text
    )
    assert "a-base" in caplog.text


def test_기준선_점수가_없으면_차이는_빈칸(tmp_path):
    root = _with_template(tmp_path)
    _exp(root, "b-exp", "a-missing", 0.7)
    assert "| field_accuracy 0.700 | - |" in build_index(root)


@pytest.mark.parametrize("drop", ["기능", "바꾼 것", "주 지표", "기준선"])
def test_카드_머리_칸이_빠지면_이유와_함께_실패(tmp_path, drop):
    root = _with_template(tmp_path)
    _exp(root, "a-base", "a-base", 0.6, drop=drop)
    with pytest.raises(EvalError, match=f"a-base.*{drop}"):
        build_index(root)


def test_카드_머리가_없으면_실패(tmp_path):
    root = _with_template(tmp_path)
    d = root / "a-base"
    d.mkdir()
    (d / "card.md").write_text("# 머리 없음\n", encoding="utf-8")
    with pytest.raises(EvalError, match="a-base.*머리"):
        build_index(root)


def test_주_지표가_scores에_없으면_실패(tmp_path):
    root = _with_template(tmp_path)
    _exp(root, "a-base", "a-base", 0.6, primary="recall@5")
    with pytest.raises(EvalError, match="a-base.*recall@5"):
        build_index(root)


def test_card가_없는_폴더는_건너뛰지_않고_실패(tmp_path):
    root = _with_template(tmp_path)
    (root / "a-base").mkdir()
    with pytest.raises(EvalError, match="a-base.*card.md"):
        build_index(root)


def test_main은_파일을_쓴다(tmp_path):
    root = _with_template(tmp_path)
    _exp(root, "a-base", "a-base", 0.6)
    out = tmp_path / "index.md"
    assert main(["--experiments-dir", str(root), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == build_index(root)


def test_main은_실패하면_1이고_파일을_안_쓴다(tmp_path):
    root = _with_template(tmp_path)
    (root / "a-base").mkdir()
    out = tmp_path / "index.md"
    assert main(["--experiments-dir", str(root), "--out", str(out)]) == 1
    assert not out.exists()
