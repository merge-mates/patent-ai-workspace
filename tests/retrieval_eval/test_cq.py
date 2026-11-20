"""CQ 후보 파일 쓰기와 모으기 (requirements 기준 5, design.md 7-1 CQ 파일, 7-5).

기대값은 design.md의 CQ 파일 칸·모으기 규칙에서 가져온다.
gold_cq_miss.jsonl: 줄 하나는 맞고(Hit), 줄 하나는 범위 안에 있지만 질의와 겹치는 낱말이 없는
[0027]-[0028]을 가리킨다 (검색이 놓친 줄 = CQ 후보). 정답 조각이 범위에 아예 없는 줄은
CQ가 아니라 excluded_gold_not_in_scope로 빠진다 (#129).
"""

import json
import logging
import shutil
from pathlib import Path

import pytest

from eval.retrieval.config import load_config
from eval.retrieval.cq import write_cq
from eval.retrieval.cq_merge import main as merge_main
from eval.retrieval.cq_merge import merge_cq
from eval.retrieval.score import main, score
from patent_ai.retrieval.repository import InMemoryChunkRepository

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "retrieval"
CHECK_CHUNKS = FIX / "chunks_check.jsonl"
MISS_ID = "10-2020-0000002:r1:c1:KR2000000001A"
FIELDS = {
    "row_id",
    "goldset_version",
    "gold_sha256",
    "corpus",
    "impl",
    "mode",
    "index_version",
    "k",
    "query",
    "items",
    "found",
    "why",
}


@pytest.fixture
def goldsets_root(tmp_path):
    root = tmp_path / "goldsets"
    (root / "tune" / "retrieval").mkdir(parents=True)
    (root / "VERSION").write_text("1\n")
    for f in FIX.glob("gold_*.jsonl"):
        shutil.copy(f, root / "tune" / "retrieval" / f.name)
    return root


def make_report(tmp_path, root, gold_name):
    text = (FIX / "config_ok.yaml").read_text(encoding="utf-8")
    cfg_text = "\n".join(
        f"gold: retrieval/{gold_name}" if ln.startswith("gold:") else ln for ln in text.splitlines()
    )
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(cfg_text + "\n", encoding="utf-8")
    cfg = load_config(cfg_path)
    repo = InMemoryChunkRepository.from_jsonl("cite", CHECK_CHUNKS)
    return score(cfg, repo, root, "abc", scores_dir=tmp_path / "out", cq_dir=tmp_path / "cq")


def read_lines(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines()]


def cq_line(row_id, version=1, sha="a" * 64):
    return {"row_id": row_id, "goldset_version": version, "gold_sha256": sha, "why": ""}


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    return path


# ---- 쓰기 -------------------------------------------------------------


def test_못_맞힌_줄만_쓰고_why는_빈칸(tmp_path, goldsets_root):
    report = make_report(tmp_path, goldsets_root, "gold_cq_miss.jsonl")
    out = tmp_path / "cq" / "cq_candidates.jsonl"
    assert write_cq(report, out) == 1  # 반환 = 쓴 줄 수
    (line,) = read_lines(out)
    assert set(line) == FIELDS
    assert line["row_id"] == MISS_ID
    assert line["why"] == ""
    assert line["k"] == 10  # 설정 k 중 가장 큰 값
    assert (line["corpus"], line["impl"], line["mode"]) == ("cite", "fake", "bm25")
    assert line["index_version"] == "cite-idx-v1"
    assert line["goldset_version"] == 1 and len(line["gold_sha256"]) == 64
    assert line["gold_sha256"] == report.scores["gold_sha256"]
    assert line["items"][0]["label"] == "[0027]-[0028]"
    assert line["query"] == "시료를 냉각하는 단계를 포함하는 처리 방법"
    # 검색에 걸린 조각 (k 안)
    assert 0 < len(line["found"]) <= 10
    assert set(line["found"][0]) == {"chunk_id", "label", "score"}


def test_후보_0건이면_경고하고_빈_파일(tmp_path, goldsets_root, caplog):
    report = make_report(tmp_path, goldsets_root, "gold_ok.jsonl")
    out = tmp_path / "cq" / "cq_candidates.jsonl"
    with caplog.at_level(logging.WARNING):
        assert write_cq(report, out) == 0
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert "가열하는" not in caplog.text  # 질의 글자 없음
    assert out.read_text(encoding="utf-8") == ""


def test_main이_cq_파일을_쓰고_건수를_scores에_넣는다(tmp_path, goldsets_root):
    cfg = tmp_path / "config.yaml"
    text = (FIX / "config_ok.yaml").read_text(encoding="utf-8")
    cfg.write_text(text.replace("gold_ok.jsonl", "gold_cq_miss.jsonl"), encoding="utf-8")
    argv = ["--config", str(cfg), "--goldsets-root", str(goldsets_root)]
    argv += ["--scores-dir", str(tmp_path / "out"), "--cq-dir", str(tmp_path / "cq")]
    argv += ["--chunks", str(CHECK_CHUNKS)]
    assert main(argv, commit="abc") == 0
    lines = read_lines(tmp_path / "cq" / "cq_candidates.jsonl")
    scores = json.loads((tmp_path / "out" / "scores.json").read_text(encoding="utf-8"))
    assert scores["failures"]["cq_candidates"] == len(lines) == 1
    raw = (tmp_path / "out" / "scores.json").read_text(encoding="utf-8")
    assert "KR2000000001A" not in raw and "냉각하는" not in raw  # scores에는 줄 ID·질의 없음


# ---- 모으기 -----------------------------------------------------------


def test_교집합만_남긴다(tmp_path):
    a = write_jsonl(tmp_path / "a.jsonl", [cq_line("r1"), cq_line("r2")])
    b = write_jsonl(tmp_path / "b.jsonl", [cq_line("r2"), cq_line("r3")])
    merged = merge_cq([a, b])
    assert [m["row_id"] for m in merged] == ["r2"]


def test_main_출력_파일(tmp_path):
    a = write_jsonl(tmp_path / "a.jsonl", [cq_line("r1"), cq_line("r2")])
    b = write_jsonl(tmp_path / "b.jsonl", [cq_line("r2")])
    out = tmp_path / "m" / "merged.jsonl"
    assert merge_main([str(a), str(b), "-o", str(out)]) == 0
    assert [x["row_id"] for x in read_lines(out)] == ["r2"]


def test_파일_1개는_그대로_복사(tmp_path):
    a = write_jsonl(tmp_path / "a.jsonl", [cq_line("r1"), cq_line("r2")])
    out = tmp_path / "merged.jsonl"
    assert merge_main([str(a), "-o", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == a.read_text(encoding="utf-8")


def test_빈_파일_1개는_복사하고_경고(tmp_path, caplog):
    a = tmp_path / "a.jsonl"
    a.write_text("", encoding="utf-8")
    out = tmp_path / "merged.jsonl"
    with caplog.at_level(logging.WARNING):
        assert merge_main([str(a), "-o", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == ""
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_파일_0개는_1(tmp_path, capsys):
    assert merge_main(["-o", str(tmp_path / "m.jsonl")]) == 1


def test_교집합_0건은_경고(tmp_path, caplog):
    a = write_jsonl(tmp_path / "a.jsonl", [cq_line("r1")])
    b = write_jsonl(tmp_path / "b.jsonl", [cq_line("r2")])
    with caplog.at_level(logging.WARNING):
        assert merge_cq([a, b]) == []
    assert any(r.levelno == logging.WARNING for r in caplog.records)


@pytest.mark.parametrize(
    ("version", "sha", "field"),
    [(2, "a" * 64, "goldset_version"), (1, "b" * 64, "gold_sha256")],
)
def test_버전이나_해시가_다르면_1과_칸_이름(tmp_path, capsys, version, sha, field):
    a = write_jsonl(tmp_path / "a.jsonl", [cq_line("r1")])
    b = write_jsonl(tmp_path / "b.jsonl", [cq_line("r1", version=version, sha=sha)])
    assert merge_main([str(a), str(b), "-o", str(tmp_path / "m.jsonl")]) == 1
    err = capsys.readouterr().err
    assert field in err
    assert not (tmp_path / "m.jsonl").exists()


def test_출력이_git_안이면_1(tmp_path, capsys):
    a = write_jsonl(tmp_path / "a.jsonl", [cq_line("r1")])
    repo_root = Path(__file__).resolve().parents[2]
    assert merge_main([str(a), "-o", str(repo_root / "docs" / "cq_merged.jsonl")]) == 1
    assert not (repo_root / "docs" / "cq_merged.jsonl").exists()


def test_메시지에_질의_글자가_없다(tmp_path, capsys):
    bad = dict(cq_line("r1", version=2), query="비밀질의글자")
    a = write_jsonl(tmp_path / "a.jsonl", [dict(cq_line("r1"), query="비밀질의글자")])
    b = write_jsonl(tmp_path / "b.jsonl", [bad])
    merge_main([str(a), str(b), "-o", str(tmp_path / "m.jsonl")])
    assert "비밀질의글자" not in capsys.readouterr().err
