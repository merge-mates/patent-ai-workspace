"""채점기 score()·CLI·scores.json (requirements 기준 3, design.md 2절 흐름 3~8, 7-1, 7-3).

기대값은 design.md 7-3 점검 예에서 가져온다 (구현을 보고 정하지 않음).
"""

import json
import shutil
from pathlib import Path

import pytest

from eval.retrieval.config import load_config
from eval.retrieval.errors import RetrievalEvalError
from eval.retrieval.score import default_cq_dir, default_scores_dir, main, score
from patent_ai.retrieval.repository import InMemoryChunkRepository

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "retrieval"
REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_CHUNKS = FIX / "chunks_check.jsonl"


@pytest.fixture
def goldsets_root(tmp_path):
    """임시 폴더에 정답 세트 구조(VERSION, tune/retrieval/)를 만든다."""
    root = tmp_path / "goldsets"
    (root / "tune" / "retrieval").mkdir(parents=True)
    (root / "VERSION").write_text("1\n")
    for f in FIX.glob("gold_*.jsonl"):
        shutil.copy(f, root / "tune" / "retrieval" / f.name)
    return root


def make_config(tmp_path, gold_name="gold_ok.jsonl", base="config_ok.yaml", extra=""):
    """맞는 설정에서 gold 줄만 바꾼 설정 파일을 임시 폴더에 만든다."""
    text = (FIX / base).read_text(encoding="utf-8")
    lines = [
        f"gold: retrieval/{gold_name}" if line.startswith("gold:") else line
        for line in text.splitlines()
    ]
    path = tmp_path / "config.yaml"
    path.write_text("\n".join(lines) + "\n" + extra, encoding="utf-8")
    return path


def run_main(tmp_path, root, *, gold_name="gold_ok.jsonl", chunks=CHECK_CHUNKS, extra=(), cfg=None):
    cfg = cfg or make_config(tmp_path, gold_name)
    argv = [
        "--config",
        str(cfg),
        "--goldsets-root",
        str(root),
        "--scores-dir",
        str(tmp_path / "out"),
        "--cq-dir",
        str(tmp_path / "cq"),
        *extra,
    ]
    if chunks is not None:
        argv += ["--chunks", str(chunks)]
    return main(argv, commit="abc")


def read_scores(tmp_path):
    return json.loads((tmp_path / "out" / "scores.json").read_text(encoding="utf-8"))


# ---- 평소 -------------------------------------------------------------


def test_점검_예_값이_나온다(tmp_path, goldsets_root):
    assert run_main(tmp_path, goldsets_root) == 0
    s = read_scores(tmp_path)
    m = s["metrics"]
    assert m["hit@5"] == 1
    assert m["recall@5"] == pytest.approx(0.5, abs=1e-3)
    assert m["random_recall@5"] == pytest.approx(0.738, abs=1e-3)
    assert m["random_hit@5"] == pytest.approx(0.996, abs=1e-3)
    assert m["recall_ratio@5"] == pytest.approx(0.68, abs=1e-2)
    assert s["n"] == 1
    assert set(s["failures"]) == {
        "excluded_no_location",
        "excluded_clarity",
        "excluded_same_as_other",
        "excluded_text_missing",
        "excluded_edition_unverified",
        "cq_candidates",
        "recall_ratio_undefined",
    }


def test_scores_json_칸과_기록값(tmp_path, goldsets_root):
    run_main(tmp_path, goldsets_root)
    s = read_scores(tmp_path)
    assert s["experiment"] == "m2-i3-retrieval-fake"
    assert s["commit"] == "abc"  # main의 commit 인자 그대로
    assert (s["goldset"], s["goldset_version"]) == ("tune", 1)
    assert (s["corpus"], s["index_version"], s["mode"], s["impl"]) == (
        "cite",
        "cite-idx-v1",
        "bm25",
        "fake",
    )
    assert s["metric_name"] == "심사관 지정 위치 회수율"
    assert len(s["gold_sha256"]) == 64
    # 모델 호출이 없으니 seconds만 채우고 나머지는 0
    cost = s["cost"]
    assert cost["usd"] == 0 and cost["external_calls"] == 0
    assert cost["input_tokens"] == 0 and cost["output_tokens"] == 0
    assert cost["seconds"] >= 0
    # k마다 키가 있다 (설정 k: 1, 3, 5, 10)
    for k in (1, 3, 5, 10):
        assert f"hit@{k}" in s["metrics"]


def test_scores_json에_row_id와_질의_글자가_없다(tmp_path, goldsets_root):
    run_main(tmp_path, goldsets_root)
    raw = (tmp_path / "out" / "scores.json").read_text(encoding="utf-8")
    assert "KR2000000001A" not in raw  # row_id 끝 부분(공보 번호)
    assert "10-2020-0000001" not in raw  # 발송번호
    assert "가열하는" not in raw  # 질의 글자


def test_score_함수가_보고서를_돌려준다(tmp_path, goldsets_root):
    cfg = load_config(make_config(tmp_path))
    repo = InMemoryChunkRepository.from_jsonl("cite", CHECK_CHUNKS)
    report = score(
        cfg, repo, goldsets_root, "abc", scores_dir=tmp_path / "out", cq_dir=tmp_path / "cq"
    )
    assert report.scores["n"] == 1
    assert report.scores["metrics"]["hit@5"] == 1


def test_chunks면_기본_출력은_work_아래다():
    d = default_scores_dir("m2-i3-x", chunks_mode=True)
    assert d.is_relative_to(REPO_ROOT / "work" / "retrieval" / "m2-i3-x")
    # 진짜 저장소면 experiments/<실험>/
    assert default_scores_dir("m2-i3-x", chunks_mode=False).is_relative_to(
        REPO_ROOT / "experiments" / "m2-i3-x"
    )
    assert default_cq_dir("m2-i3-x").is_relative_to(REPO_ROOT / "work" / "retrieval" / "m2-i3-x")


def test_실험_이름에_경로_조각이_있으면_막는다():
    with pytest.raises(RetrievalEvalError):
        default_scores_dir("../x", chunks_mode=True)


# ---- 빈 입력 ----------------------------------------------------------


def test_빼는_줄을_이유별로_센다(tmp_path, goldsets_root):
    # chunks_cite.jsonl에는 KR1000000001A가 있다
    cfg = load_config(make_config(tmp_path, "gold_excluded.jsonl"))
    repo = InMemoryChunkRepository.from_jsonl("cite", FIX / "chunks_cite.jsonl")
    report = score(
        cfg, repo, goldsets_root, "abc", scores_dir=tmp_path / "out", cq_dir=tmp_path / "cq"
    )
    f = report.scores["failures"]
    assert f["excluded_no_location"] == 1
    assert f["excluded_clarity"] == 1
    assert f["excluded_same_as_other"] == 1
    assert report.scores["n"] == 2  # 종속항 줄·맞는 조각 없는 줄은 점수에 들어간다


def test_본문_없는_공보는_text_missing으로_빠진다(tmp_path, goldsets_root):
    # chunks_check.jsonl에는 KR1000000001A 조각이 없다 -> 남은 두 줄이 text_missing
    # (나머지 세 줄은 exclude) -> 남은 줄 0개라 실패
    cfg = load_config(make_config(tmp_path, "gold_excluded.jsonl"))
    repo = InMemoryChunkRepository.from_jsonl("cite", CHECK_CHUNKS)
    with pytest.raises(RetrievalEvalError, match="0개"):
        score(cfg, repo, goldsets_root, "abc", scores_dir=tmp_path / "out", cq_dir=tmp_path / "cq")


def test_모두_빠지면_main이_1을_돌려준다(tmp_path, goldsets_root):
    assert run_main(tmp_path, goldsets_root, gold_name="gold_all_excluded.jsonl") == 1
    assert not (tmp_path / "out" / "scores.json").exists()


def test_법령_판본_모름_줄은_빠진다(tmp_path, goldsets_root):
    cfg = load_config(make_config(tmp_path, "gold_law_excluded.jsonl", base="config_law_ok.yaml"))
    repo = InMemoryChunkRepository.from_jsonl("law", FIX / "chunks_law.jsonl")
    with pytest.raises(RetrievalEvalError, match="0개"):
        score(cfg, repo, goldsets_root, "abc", scores_dir=tmp_path / "out", cq_dir=tmp_path / "cq")


def test_무작위_분모가_0이면_배수_키를_뺀다(tmp_path, goldsets_root):
    # 정답 항목에 맞는 조각이 범위에 하나도 없는 줄만 둔다
    lines = (FIX / "gold_excluded.jsonl").read_text(encoding="utf-8").splitlines()
    only = [ln for ln in lines if '"ex-no-match"' in ln]
    assert len(only) == 1
    (goldsets_root / "tune" / "retrieval" / "gold_nomatch.jsonl").write_text(only[0] + "\n")
    cfg = load_config(make_config(tmp_path, "gold_nomatch.jsonl"))
    repo = InMemoryChunkRepository.from_jsonl("cite", FIX / "chunks_cite.jsonl")
    report = score(
        cfg, repo, goldsets_root, "abc", scores_dir=tmp_path / "out", cq_dir=tmp_path / "cq"
    )
    assert "recall_ratio@5" not in report.scores["metrics"]
    assert report.scores["metrics"]["random_recall@5"] == 0
    # k 목록(1, 3, 5, 10)마다 한 번씩 센다
    assert report.scores["failures"]["recall_ratio_undefined"] == 4


# ---- 실패 -------------------------------------------------------------


def test_chunks가_없으면_Postgres_안내와_1(tmp_path, goldsets_root, capsys):
    assert run_main(tmp_path, goldsets_root, chunks=None) == 1
    assert "Postgres 저장소 없음(m2-i2)" in capsys.readouterr().err


def test_줄_검색_예외는_main이_1을_돌려준다(tmp_path, goldsets_root, capsys):
    # vector 검색인데 녹화에 없는 질의 -> RecordedEmbeddingMissing -> 조용히 넘기지 않고 실패
    cfg = make_config(tmp_path)
    text = cfg.read_text(encoding="utf-8").replace("mode: bm25", "mode: vector")
    text += f"  query_vectors: {FIX / 'query_vectors.json'}\n"
    cfg.write_text(text, encoding="utf-8")
    assert run_main(tmp_path, goldsets_root, cfg=cfg) == 1
    err = capsys.readouterr().err
    assert "가열하는" not in err  # 질의 글자는 메시지에 없다
    assert not (tmp_path / "out" / "scores.json").exists()


def test_chunks와_experiments_scores_dir이면_1과_파일_없음(tmp_path, goldsets_root):
    target = REPO_ROOT / "experiments" / "x-score-test"
    assert not target.exists()
    cfg = make_config(tmp_path)
    argv = [
        "--config",
        str(cfg),
        "--goldsets-root",
        str(goldsets_root),
        "--chunks",
        str(CHECK_CHUNKS),
        "--scores-dir",
        str(target),
        "--cq-dir",
        str(tmp_path / "cq"),
    ]
    assert main(argv, commit="abc") == 1
    assert not target.exists()


# ---- 제외 건수 키 ------------------------------------------------------


def test_text_missing_건수가_1이다(tmp_path, goldsets_root):
    # 점수에 드는 줄 하나(gold_ok와 같음) + 조각이 없는 공보 줄 하나
    cfg = load_config(make_config(tmp_path, "gold_cite_counts.jsonl"))
    repo = InMemoryChunkRepository.from_jsonl("cite", CHECK_CHUNKS)
    report = score(
        cfg, repo, goldsets_root, "abc", scores_dir=tmp_path / "out", cq_dir=tmp_path / "cq"
    )
    assert report.scores["n"] == 1
    assert report.scores["failures"]["excluded_text_missing"] == 1
    assert report.scores["failures"]["excluded_edition_unverified"] == 0


def test_edition_unverified_건수가_1이다(tmp_path, goldsets_root):
    # 판본 확인된 줄 하나 + 판본 모름 줄 하나
    cfg = load_config(make_config(tmp_path, "gold_law_counts.jsonl", base="config_law_ok.yaml"))
    repo = InMemoryChunkRepository.from_jsonl("law", FIX / "chunks_law.jsonl")
    report = score(
        cfg, repo, goldsets_root, "abc", scores_dir=tmp_path / "out", cq_dir=tmp_path / "cq"
    )
    assert report.scores["n"] == 1
    assert report.scores["failures"]["excluded_edition_unverified"] == 1
    assert report.scores["failures"]["excluded_text_missing"] == 0


def test_기준일로_범위가_비면_row_id만_담아_멈춘다(tmp_path, goldsets_root, capsys):
    """[사람 판단 대기] design 2절과 다름: 지금은 멈춘다 (행동을 고정해 둔 테스트)."""
    cfg = make_config(tmp_path, "gold_law_scope_empty.jsonl", base="config_law_ok.yaml")
    repo = InMemoryChunkRepository.from_jsonl("law", FIX / "chunks_law.jsonl")
    with pytest.raises(RetrievalEvalError) as ei:
        score(
            load_config(cfg),
            repo,
            goldsets_root,
            "abc",
            scores_dir=tmp_path / "out",
            cq_dir=tmp_path / "cq",
        )
    assert "cnt-law-early" in str(ei.value)
    assert "진보성 판단" not in str(ei.value)
    # main도 1을 돌려주고 질의 글자를 찍지 않는다
    assert run_main(tmp_path, goldsets_root, chunks=FIX / "chunks_law.jsonl", cfg=cfg) == 1
    err = capsys.readouterr().err
    assert "cnt-law-early" in err and "진보성 판단" not in err
    assert not (tmp_path / "out" / "scores.json").exists()
