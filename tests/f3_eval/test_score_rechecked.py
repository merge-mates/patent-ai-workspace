"""`*_rechecked` 지표 테스트: 1차에 못 찾아 2차(round 2) 검색을 한 줄만 따로 센다.

기대값은 recheck design 7-2와 구현 계획 m3-i2-309b task-5. 지어낸 정답·예측(tmp)만 쓴다.
정답: 청구항 1 = [0014], [0080]-[0081]. 문단 14는 정답, 20은 아님.
"""

import json

import pytest
from f3_eval_builder import prediction, write_chunks, write_goldset, write_run

from eval.f3.score import main


@pytest.fixture
def run(tmp_path_factory):
    def go(pred, *, other=None):
        tmp_path = tmp_path_factory.mktemp("run")  # 부를 때마다 새 폴더
        root = tmp_path / "goldsets"
        write_goldset(root)
        preds = tmp_path / "preds"
        write_run(preds, pred)
        args = ["--goldsets-root", str(root), "--predictions", str(preds)]
        if other is not None:
            ref = tmp_path / "ref"
            write_run(ref, other)
            args += ["--rechecked-rows-from", str(ref)]
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "experiment: m2-f3-x\nfeature: f3\ngoldset: tune\ngoldset_version: 1\n"
            "impl: split_search\nindex_version: cite-idx-v2\nk: 10\n",
            encoding="utf-8",
        )
        out = tmp_path / "out"
        args += ["--config", str(cfg), "--chunks", str(write_chunks(tmp_path / "c.jsonl"))]
        args += ["--scores-dir", str(out), "--cq-dir", str(tmp_path / "cq")]
        assert main(args) == 0
        return json.loads((out / "scores.json").read_text("utf-8"))

    return go


def test_2차_검색_기록이_있는_줄만_따로_센다(run):
    # 구성요소 2가 2차에서 [0014]를 찾음. 그 줄(청구항 1 x 문헌)이 대상 1줄
    pred = prediction(searched=((1, [20]), (2, [14])), selected=(14,), rounds={2: 2})
    s = run(pred)
    m = s["metrics"]
    assert m["rechecked_rows"] == 1
    assert m["search_recall_rechecked"] == 0.5
    assert m["selected_recall_rechecked"] == 0.5
    assert "search_recall_rechecked" not in s["skipped_metrics"]


def test_2차_기록이_없으면_지표를_빼고_이유를_남긴다(run):
    s = run(prediction())
    m = s["metrics"]
    assert not {"search_recall_rechecked", "selected_recall_rechecked", "rechecked_rows"} & set(m)
    assert s["skipped_metrics"]["search_recall_rechecked"] == "다시 찾은 줄 없음"
    assert s["skipped_metrics"]["selected_recall_rechecked"] == "다시 찾은 줄 없음"


def test_rechecked_rows_from의_줄_집합을_쓴다(run):
    # 자기 예측엔 2차 기록이 없지만 다른 예측(판 A)엔 있다 -> 그 줄이 분모
    mine = prediction(searched=((1, [14]),), selected=(14,))
    ref = prediction(searched=((1, [20]), (2, [14])), rounds={2: 2})
    m = run(mine, other=ref)["metrics"]
    assert m["rechecked_rows"] == 1
    assert m["search_recall_rechecked"] == 0.5 and m["selected_recall_rechecked"] == 0.5


def test_rechecked_rows_from에_2차_기록이_없으면_자기_2차_기록도_안_센다(run):
    mine = prediction(searched=((1, [14]), (2, [14])), rounds={2: 2})
    s = run(mine, other=prediction())
    assert "rechecked_rows" not in s["metrics"]
    assert s["skipped_metrics"]["rechecked_rows"] == "다시 찾은 줄 없음"


def test_기존_지표_값은_그대로다(run):
    pred = prediction(searched=((1, [20]), (2, [14])), selected=(14,), rounds={2: 2})
    with_ref = run(pred, other=prediction(searched=((1, [20]),)))["metrics"]
    base = run(pred)["metrics"]
    for k in ("search_recall", "selected_recall", "search_hit", "search_recall_round1"):
        assert with_ref[k] == base[k]
