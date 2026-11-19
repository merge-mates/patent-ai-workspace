"""F1 채점 명령 (eval.f1.score main): 정답 폴더 + 예측 OAResult 파일 + (쪽 글자) -> scores.json."""

import json
from pathlib import Path

import pytest
from f1_oa_builder import PAGES

import eval.run_eval as run_eval
from eval.f1.score import main
from patent_ai.core.schemas.common import Status, StatusValue
from patent_ai.core.schemas.document import Page, PageText

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "f1_eval"
REPO_ROOT = Path(__file__).resolve().parents[2]
KEY = "1020990000001_952099000000001"
OK = Status(value=StatusValue.CONFIRMED, checked="글자 층 있음")


@pytest.fixture
def setup(tmp_path, make_oa):
    root = tmp_path / "goldsets"
    (root / "tune" / "f1").mkdir(parents=True)
    (root / "VERSION").write_text("1\n")
    (root / "tune" / "f1" / f"{KEY}.json").write_text(
        (FIX / "gold_ok.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    preds = tmp_path / "preds"
    preds.mkdir()
    (preds / f"{KEY}.json").write_text(make_oa().model_dump_json(), encoding="utf-8")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "experiment: m1-i3-f1-x\nfeature: f1\ngoldset: tune\ngoldset_version: 1\nimpl: jaea\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    args = [
        "--config",
        str(cfg),
        "--goldsets-root",
        str(root),
        "--predictions",
        str(preds),
        "--scores-dir",
        str(out),
    ]
    return {"root": root, "preds": preds, "cfg": cfg, "out": out, "args": args, "tmp": tmp_path}


def _scores(out: Path) -> dict:
    return json.loads((out / "scores.json").read_text(encoding="utf-8"))


def _pages_file(d: Path) -> None:
    pt = PageText(
        document_id="doc-1",
        pages=[Page(page=i, text=t, status=OK) for i, t in enumerate(PAGES, 1)],
        status=OK,
    )
    d.mkdir(exist_ok=True)
    (d / f"{KEY}.pages.json").write_text(pt.model_dump_json(), encoding="utf-8")


def test_정답과_같은_예측이면_scores에_1이_남는다(setup):
    assert main(setup["args"]) == 0
    s = _scores(setup["out"])
    assert s["n"] == 1
    assert s["goldset_version"] == 1
    assert s["metrics"]["field_accuracy"] == 1
    assert s["failures"]["pages_missing"] == 1  # 쪽 글자를 안 줌
    assert len(s["gold_sha256"]) == 64
    assert KEY not in json.dumps(s)


def test_쪽_글자를_주면_원문_위치를_센다(setup):
    _pages_file(setup["tmp"] / "pages")
    assert main(setup["args"] + ["--pages", str(setup["tmp"] / "pages")]) == 0
    s = _scores(setup["out"])
    assert s["metrics"]["unverified_locations"] == 0
    assert s["failures"]["pages_missing"] == 0


def test_run_eval이_feature_f1로_이_명령을_부른다(setup):
    assert run_eval.SCORERS["f1"] is main
    assert run_eval.main(setup["args"]) == 0
    assert _scores(setup["out"])["metrics"]["field_accuracy"] == 1


def test_VERSION이_다르면_실패(setup, capsys):
    (setup["root"] / "VERSION").write_text("2\n")
    assert main(setup["args"]) == 1
    assert "goldset_version" in capsys.readouterr().err


def test_예측_파일이_틀리면_순번만_말하고_실패(setup, capsys):
    (setup["preds"] / f"{KEY}.json").write_text('{"oa_id": 1}', encoding="utf-8")
    assert main(setup["args"]) == 1
    err = capsys.readouterr().err
    assert "예측 파일 1번째" in err
    assert KEY not in err
    assert not (setup["out"] / "scores.json").exists()


def test_정답에_없는_예측은_경고만(setup, make_oa, caplog):
    (setup["preds"] / "1020990000999_952099000000999.json").write_text(
        make_oa().model_dump_json(), encoding="utf-8"
    )
    assert main(setup["args"]) == 0
    assert "정답에 없는 예측 1건" in caplog.text


def test_예측_폴더가_git에_들어갈_수_있으면_실패(setup, capsys):
    args = list(setup["args"])
    args[args.index("--predictions") + 1] = str(REPO_ROOT / "docs" / "preds-x")
    assert main(args) == 1
    assert "git" in capsys.readouterr().err


def test_예측_폴더가_없으면_실패(setup, capsys):
    args = list(setup["args"])
    args[args.index("--predictions") + 1] = str(setup["tmp"] / "nope")
    assert main(args) == 1
    assert "예측 폴더" in capsys.readouterr().err


def test_가짜_정답으로_돌리면_기본_출력은_work_아래(setup):
    from eval.f1.score import default_scores_dir

    # 진짜 정답 폴더(…/data/goldsets)일 때만 experiments/<실험>/
    assert (
        default_scores_dir(REPO_ROOT / "data" / "goldsets", "e1")
        == REPO_ROOT / "experiments" / "e1"
    )
    assert default_scores_dir(setup["root"], "e1") == REPO_ROOT / "work" / "f1" / "e1"


def test_변환에서_틀리면_순번만_말하고_실패(setup, make_oa, capsys):
    oa = make_oa()
    r1 = oa.rejections[0]
    bad = r1.model_copy(
        update={"citations": [c.model_copy(update={"label": "인용1"}) for c in r1.citations]}
    )
    oa = oa.model_copy(update={"rejections": [bad, *oa.rejections[1:]]})
    (setup["preds"] / f"{KEY}.json").write_text(oa.model_dump_json(), encoding="utf-8")
    assert main(setup["args"]) == 1
    err = capsys.readouterr().err
    assert "예측 파일 1번째" in err
    assert "인용1" not in err
