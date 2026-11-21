"""F3 채점기 테스트 (B9): 가짜 정답·예측(tmp)으로 지표·실패 건수·CQ·종료 코드를 본다.

기대값은 구현 계획 B9, docs/evaluation/search-gold.md 2절 3번(겹침), f3-compare-gold.md 1절.
진짜 정답(data/goldsets)은 열지 않는다.
"""

import json
import logging
from pathlib import Path

import pytest
from f3_eval_builder import (
    KEY,
    novelty_table,
    prediction,
    write_chunks,
    write_goldset,
    write_run,
)

import eval.run_eval as run_eval
from eval.common.scores import check_scores
from eval.f3.score import EXIT_NO_GOLD, main


@pytest.fixture
def run(tmp_path):
    """채점 명령을 돌려 (종료 코드, scores 또는 None, CQ 줄 목록)을 돌려주는 함수."""

    def go(
        pred=None,
        *,
        goldset=None,
        inputs=True,
        entry=main,
        extra=(),
        key=KEY,
        index_version="cite-idx-v2",
        write=True,
    ):
        root = tmp_path / "goldsets"
        if goldset is None:
            write_goldset(root)
        else:
            goldset(root)
        preds = tmp_path / "preds"
        preds.mkdir(exist_ok=True)
        if write:
            write_run(preds, pred if pred is not None else prediction(), inputs=inputs, key=key)
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "experiment: m2-f3-x\nfeature: f3\ngoldset: tune\ngoldset_version: 1\n"
            f"impl: split_search\nindex_version: {index_version}\nk: 10\n",
            encoding="utf-8",
        )
        out, cq = tmp_path / "out", tmp_path / "cq"
        args = ["--config", str(cfg), "--goldsets-root", str(root), "--predictions", str(preds)]
        args += ["--chunks", str(write_chunks(tmp_path / "chunks.jsonl"))]
        args += ["--scores-dir", str(out), "--cq-dir", str(cq), *extra]
        code = entry(args)
        scores_file = out / "scores.json"
        scores = json.loads(scores_file.read_text("utf-8")) if scores_file.is_file() else None
        cq_file = cq / "cq_candidates.jsonl"
        lines = (
            [json.loads(x) for x in cq_file.read_text("utf-8").splitlines()]
            if cq_file.is_file()
            else None
        )
        return code, scores, lines

    return go


# ---- ① 심사관 지정 문단 재현율: 검색 단계와 모델이 고른 것을 따로 ----
def test_검색_재현율과_고른_문단_재현율을_따로_낸다(run):
    # 정답 [0014], [0080]-[0081] / 검색 상위 k 합집합 {14, 20} / 모델이 고른 것 {20}
    code, scores, _ = run()
    assert code == 0
    m = scores["metrics"]
    assert (m["search_hit"], m["search_recall"]) == (1.0, 0.5)
    assert (m["selected_hit"], m["selected_recall"]) == (0.0, 0.0)
    assert scores["metric_name"] == "심사관 지정 위치 회수율"
    assert scores["failures"]["excluded_no_location"] == 1  # 위치 없음 줄은 뺀다


def test_무작위_기준선과_비율을_같이_낸다(run):
    # 범위 조각 N=4 (14, 20, 80, 81), 맞는 조각 수 [1, 2],
    # 검색이 가져온 조각 k=2 ({14, 20}).
    # 항목별 확률: 1 - C(3,2)/C(4,2) = 1/2, 1 - C(2,2)/C(4,2) = 5/6 -> 평균 2/3.
    # Hit: 합집합 3개 -> 1 - C(1,2)/C(4,2) = 1. search_recall 0.5 / (2/3) = 0.75
    _, scores, _ = run()
    m = scores["metrics"]
    assert m["random_search_recall"] == pytest.approx(2 / 3)
    assert m["random_search_hit"] == pytest.approx(1.0)
    assert m["search_recall_ratio"] == pytest.approx(0.75)


def test_가져온_조각이_없으면_무작위도_0이고_비율은_빼고_이유를_남긴다(run):
    _, scores, _ = run(prediction(searched=(), selected=()))
    m = scores["metrics"]
    assert m["random_search_recall"] == 0.0 and m["random_search_hit"] == 0.0
    assert "search_recall_ratio" not in m
    assert "search_recall_ratio" in scores["skipped_metrics"]


def test_범위_정답은_그_안_문단_하나라도_가져오면_맞음(run):
    pred = prediction(searched=((1, [81]),), selected=(14, 81))
    _, scores, _ = run(pred)
    m = scores["metrics"]
    assert (m["search_hit"], m["search_recall"]) == (1.0, 0.5)  # [0080]-[0081]만
    assert (m["selected_hit"], m["selected_recall"]) == (1.0, 1.0)


def test_심사관_지정_줄이_있는_예측은_오염이라_채점을_멈춘다(run, capsys):
    code, scores, _ = run(prediction(source="examiner"))
    assert code == 1 and scores is None
    assert "심사관 지정" in capsys.readouterr().err


def test_그_청구항을_찾은_기록이_없으면_0점으로_세고_건수를_남긴다(run):
    _, scores, _ = run(prediction(searched=(), selected=()))
    assert scores["metrics"]["search_recall"] == 0.0
    assert scores["failures"]["not_searched_rows"] == 1


# ---- 못 찾은 질문(CQ) ----
def test_검색이_정답_문단을_하나도_못_덮은_질문은_CQ로_쌓는다(run):
    code, scores, cq = run(prediction(searched=((1, [20]), (2, [20])), selected=()))
    assert code == 0 and scores["failures"]["cq_candidates"] == 1
    (line,) = cq
    assert line["claim"] == 1 and line["doc_id"] == "KR20990000001A"
    assert line["element_nos"] == [1, 2] and line["goldset_version"] == 1
    assert {"row_id", "gold_sha256", "index_version", "k", "items", "found", "why"} <= set(line)


def test_검색_기록이_없는_줄은_CQ에_넣지_않고_안_찾은_줄로만_센다(run):
    _, scores, cq = run(prediction(searched=(), selected=()))
    assert scores["failures"]["not_searched_rows"] == 1
    assert scores["failures"]["cq_candidates"] == 0 and cq == []


def test_CQ의_구성요소_번호는_그_청구항_것만_두고_부모_것은_따로_둔다(run):
    # 구성요소 2는 부모(청구항 9)에서 온 것: 청구항 1의 1번과 번호가 겹치지 않게 갈라 쓴다
    pred = prediction(searched=((1, [20]), (2, [20])), selected=(), element_claims={1: 1, 2: 9})
    _, _, cq = run(pred)
    (line,) = cq
    assert line["element_nos"] == [1]
    assert line["parent_element_nos"] == [[9, 2]]
    assert line["found"] == ["cite-idx-v2:KR20990000001A:p0020"]  # 부모 검색 조각도 그대로 센다


def test_CQ가_0건이면_경고한다(run, caplog):
    with caplog.at_level(logging.WARNING):
        _, scores, cq = run()
    assert cq == [] and scores["failures"]["cq_candidates"] == 0
    assert any("CQ" in r.getMessage() and "0건" in r.getMessage() for r in caplog.records)


# ---- ② 신규성 한 문헌 규칙 ----
def test_신규성_표가_인용_하나와만_대비하면_위반_0건(run):
    _, scores, _ = run(prediction(novelty_tables=[novelty_table([True, False], ["D1"])]))
    assert scores["failures"]["novelty_multi_citation"] == 0
    assert scores["metrics"]["novelty_tables"] == 1


@pytest.mark.parametrize(
    ("compared", "row_labels"),
    [([True, True], ["D1"]), ([True, False], ["D1", "D2"]), ([False, False], [])],
)
def test_신규성_표가_두_문헌을_합치면_위반으로_센다(run, compared, row_labels):
    _, scores, _ = run(prediction(novelty_tables=[novelty_table(compared, row_labels)]))
    assert scores["failures"]["novelty_multi_citation"] == 1


# ---- ③ 명확성 문구 위치 ----
def test_명확성_문구_위치가_청구항_글자와_겹치면_맞음(run):
    _, scores, _ = run()
    assert scores["metrics"]["clarity_term_reviewed"] == 1.0


def test_명확성_문구_위치가_안_겹치면_틀림(run):
    _, scores, _ = run(prediction(clarity_location="청구항 2 [글자 0-3]"))
    assert scores["metrics"]["clarity_term_reviewed"] == 0.0


def test_위치를_못_정한_검토는_틀림(run):
    _, scores, _ = run(prediction(clarity_location="청구항 2 (위치 확인되지 않음)"))
    assert scores["metrics"]["clarity_term_reviewed"] == 0.0


def test_청구항_글자_입력이_없으면_명확성_위치는_건너뛰고_그_사실을_남긴다(run, capsys):
    code, scores, _ = run(inputs=False)
    assert code == 0 and "clarity_term_reviewed" not in scores["metrics"]
    assert scores["failures"]["clarity_no_claim_text"] == 1
    assert "clarity_term_reviewed" in scores["skipped_metrics"]


# ---- 정답이 없는 지표 ----
def test_사람_검수_정답이_필요한_지표는_정답_없음으로_건너뛴다(run, capsys):
    _, scores, _ = run()
    skipped = scores["skipped_metrics"]
    for name in ("clarity_definition_recall", "clarity_issue_type", "novelty_difference_recall"):
        assert skipped[name] == "정답 없음" and name not in scores["metrics"]
    assert "정답 없음" in capsys.readouterr().err


def test_정답_폴더가_없으면_종료_코드_3이고_scores를_쓰지_않는다(run, capsys):
    code, scores, _ = run(goldset=lambda root: (root / "VERSION").parent.mkdir(parents=True))
    assert code == EXIT_NO_GOLD == 3 and scores is None
    assert "정답 없음" in capsys.readouterr().err


def test_검색_정답만_있어도_채점하고_명확성은_건너뛴다(run):
    code, scores, _ = run(goldset=lambda root: write_goldset(root, f1=False))
    assert code == 0 and "search_recall" in scores["metrics"]
    assert scores["skipped_metrics"]["clarity_term_reviewed"] == "정답 없음"


# ---- 예측·명령 ----
def test_정답_파일이_하나도_없으면_종료_코드_3(run):
    code, scores, _ = run(goldset=lambda root: write_goldset(root, cite=False, f1=False))
    assert code == 3 and scores is None


def test_정답_OA와_맞는_예측이_하나도_없으면_실패한다(run, capsys):
    code, scores, _ = run(key="1020990000009_952099000000009")
    assert code == 1 and scores is None
    assert "맞지 않는다" in capsys.readouterr().err


def test_run_eval이_feature_f3으로_이_채점기를_부른다(run):
    code, scores, _ = run(entry=run_eval.main)
    assert code == 0 and scores["experiment"] == "m2-f3-x"


def test_scores는_스키마_필수_칸을_갖고_번호와_원문이_없다(run):
    _, scores, _ = run()
    check_scores(scores)
    assert scores["n"] == 1 and scores["goldset_version"] == 1 and scores["gold_sha256"]
    dumped = json.dumps(scores, ensure_ascii=False)
    for secret in ("1020990000001", "952099000000001", "질의 글자", "프리뷰"):
        assert secret not in dumped
    assert scores["cost"]["external_calls"] == 0


def test_예측_폴더가_git에_들어갈_수_있는_경로면_멈춘다(run, capsys):
    repo_root = Path(__file__).resolve().parents[2]
    code, _, _ = run(extra=["--predictions", str(repo_root / "tests")])
    assert code == 1 and "git" in capsys.readouterr().err


def test_예측이_없는_OA는_0점으로_세고_건수를_남긴다(run):
    def with_other_oa(root):
        write_goldset(root)
        path = root / "tune" / "retrieval" / "cite_gold.jsonl"
        first = json.loads(path.read_text("utf-8").splitlines()[0])
        first["row_id"] = first["row_id"].replace("952099000000001", "952099000000002")
        path.write_text(path.read_text("utf-8") + json.dumps(first, ensure_ascii=False) + "\n")

    code, scores, _ = run(goldset=with_other_oa)
    assert code == 0 and scores["failures"]["missing_prediction"] == 1
    assert scores["metrics"]["search_recall"] == 0.25  # OA 평균: (0.5 + 0) / 2
    assert scores["n"] == 2


# ---- B9 리뷰 고침 ----
def test_검색_정답_줄이_전부_빠지면_점수_없이_멈춘다(run, capsys):
    # 설정의 색인 판에 조각이 하나도 없다 (판 이름 오타, DB에 그 판 없음).
    # 명확성 점수만으로 성공하지 않는다
    code, scores, _ = run(prediction(searched=(), selected=()), index_version="cite-idx-v3")
    assert code == 1 and scores is None
    assert "0개" in capsys.readouterr().err


def test_예측을_만든_색인_판이_설정과_다르면_멈춘다(run, capsys):
    # chunk_id 앞에 판이 붙어 있어, 판이 다르면 겹침이 늘 0이 되어 0점이 정상처럼 보인다
    code, scores, _ = run(index_version="cite-idx-v3")
    assert code == 1 and scores is None
    assert "색인 판" in capsys.readouterr().err


def test_예측_폴더가_비어_있으면_멈춘다(run, capsys):
    code, scores, _ = run(write=False)
    assert code == 1 and scores is None
    assert "예측" in capsys.readouterr().err


def test_심사관_위치_기록만_있어도_오염이라_멈춘다(run, capsys):
    pred = prediction()
    pred["examiner_locations"] = [{"claim": 1, "citation": "D1", "location": "[0014]"}]
    code, scores, _ = run(pred)
    assert code == 1 and scores is None
    assert "심사관 지정" in capsys.readouterr().err


def test_여러_곳_꼬리가_붙은_위치도_읽는다(run):
    _, scores, _ = run(prediction(clarity_location="청구항 2 [글자 10-19] (2곳 중 첫 자리)"))
    assert scores["metrics"]["clarity_term_reviewed"] == 1.0
    assert scores["failures"]["clarity_location_unreadable"] == 0


def test_위치_꼴을_못_읽은_검토는_건수를_남긴다(run):
    _, scores, _ = run(prediction(clarity_location="청구항 2 (위치 확인되지 않음)"))
    assert scores["failures"]["clarity_location_unreadable"] == 1
