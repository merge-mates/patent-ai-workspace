"""색인 명령 (가짜 추출기, 지어낸 글자만). 기대값은 tasks.md m2-i1 task-4에서 가져온다."""

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from patent_ai.retrieval.cite_index.__main__ import build_index, main
from patent_ai.retrieval.cite_index.pages import PageText

REPO = Path(__file__).resolve().parents[2]
CONFIG = yaml.safe_load((REPO / "config" / "cite_search.yaml").read_text(encoding="utf-8"))


class FakeExtractor:
    """파일 이름 -> 쪽 목록. 값이 예외면 던진다."""

    def __init__(self, by_name: dict):
        self.by_name = by_name
        self.calls = 0

    def extract(self, pdf_path: Path):
        self.calls += 1
        v = self.by_name[pdf_path.name]
        if isinstance(v, Exception):
            raise v
        return v


KR_PAGES = [
    PageText(
        page=1,
        lines=[
            "청구범위",
            "청구항 1",
            "지어낸 장치는 지어낸 부품을 포함한다.",
            "청구항 2",
            "제1항에 있어서 부품이 둥글다.",
        ],
    ),
]
PAPER_PAGES = [
    PageText(page=1, lines=["Made up paper page one text."]),
    PageText(page=2, lines=["Made up paper page two text."]),
]


@pytest.fixture
def env(tmp_path):
    """raw_root에 사건 폴더 둘, 표, 설정을 tmp_path에 만든다."""
    raw = tmp_path / "raw"
    for case, names in {"c1": ["KR100A.pdf", "NPL_a.pdf"], "c2": ["KR100A.pdf"]}.items():
        (raw / case).mkdir(parents=True)
        for n in names:
            (raw / case / n).write_bytes(b"%PDF fake " + n.encode())
    (raw / "_meta").mkdir()
    (raw / "_meta" / "KR999A.pdf").write_bytes(b"ignored")
    (raw / "c1" / "memo.txt").write_text("PDF 아님", encoding="utf-8")
    table = tmp_path / "ids.yaml"
    table.write_text(
        yaml.safe_dump({"doc_ids": {"NPL_a": "NPL-Made-2020"}, "skip": []}), encoding="utf-8"
    )
    cfg = dict(CONFIG)
    cfg.update(
        raw_root=str(raw),
        doc_id_table=str(table),
        report_dir=str(tmp_path / "work"),
    )
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    ext = FakeExtractor({"KR100A.pdf": KR_PAGES, "NPL_a.pdf": PAPER_PAGES})
    return cfg, cfg_path, ext, tmp_path, table


def test_문헌_둘을_조각과_보고로_만든다(env):
    cfg, _, ext, tmp, _ = env
    chunks, report = build_index(cfg, ext)
    assert {c.doc_id for c in chunks} == {"KR100A", "NPL-Made-2020"}
    assert all(c.index_version == "cite-idx-v1" for c in chunks)
    kr = [c for c in chunks if c.doc_id == "KR100A"]
    assert {c.chunk_kind for c in kr} == {"claim"}
    assert len(kr) == 2
    r = report.to_dict()
    assert r["docs"]["KR100A"]["pages"] == 1
    assert r["docs"]["KR100A"]["chunks"] == {"claim": 2}
    assert r["docs"]["NPL-Made-2020"]["pages"] == 2
    assert r["docs"]["NPL-Made-2020"]["chunks"] == {"body": 2}
    assert r["totals"]["chunks"] == 4 and r["totals"]["docs"] == 2
    assert "removed_lines" in r["docs"]["KR100A"] and "warnings" in r["docs"]["KR100A"]
    saved = json.loads(
        (tmp / "work" / "cite-idx-v1" / "index_report.json").read_text(encoding="utf-8")
    )
    assert saved["totals"]["chunks"] == 4


def test_같은_공보가_두_폴더에_있으면_한_번만_추출한다(env):
    cfg, _, ext, _, _ = env
    build_index(cfg, ext)
    assert ext.calls == 2  # KR100A 한 번 + NPL_a 한 번


def test_두_번_돌려도_조각이_같다(env):
    cfg, _, ext, _, _ = env
    a, _ = build_index(cfg, ext)
    b, _ = build_index(cfg, ext)
    assert [c.model_dump() for c in a] == [c.model_dump() for c in b]


def test_같은_doc_id인데_내용_sha가_다르면_경고(env):
    cfg, _, ext, tmp, _ = env
    (tmp / "raw" / "c2" / "KR100A.pdf").write_bytes(b"%PDF other bytes")
    _, report = build_index(cfg, ext)
    assert any("sha256" in w for w in report.to_dict()["warnings"])


def test_추출_오류는_그_문헌만_건너뛰고_보고에_남긴다(env):
    cfg, _, _, _, _ = env
    ext = FakeExtractor({"KR100A.pdf": KR_PAGES, "NPL_a.pdf": RuntimeError("깨진 PDF")})
    chunks, report = build_index(cfg, ext)
    assert {c.doc_id for c in chunks} == {"KR100A"}
    skipped = report.to_dict()["skipped"]
    assert len(skipped) == 1 and skipped[0]["file"] == "NPL_a"
    assert "깨진 PDF" in skipped[0]["reason"]


def test_표에_없는_PDF는_건너뛰고_경고와_보고(env, caplog):
    cfg, _, _, tmp, _ = env
    (tmp / "raw" / "c1" / "mystery.pdf").write_bytes(b"%PDF m")
    ext = FakeExtractor({"KR100A.pdf": KR_PAGES, "NPL_a.pdf": PAPER_PAGES})
    with caplog.at_level("WARNING"):
        chunks, report = build_index(cfg, ext)
    assert "mystery" in {s["file"] for s in report.to_dict()["skipped"]}
    assert any("mystery" in r.message for r in caplog.records)
    assert "mystery.pdf" not in ext.by_name and ext.calls == 2


def test_skip_표의_파일은_이유와_함께_건너뛴다(env):
    cfg, _, ext, _, table = env
    table.write_text(yaml.safe_dump({"doc_ids": {}, "skip": ["NPL_a"]}), encoding="utf-8")
    chunks, report = build_index(cfg, ext)
    assert {c.doc_id for c in chunks} == {"KR100A"}
    assert [s["reason"] for s in report.to_dict()["skipped"]] == ["skip 표"]


def test_cli_보고를_쓰고_요약을_찍는다(env, capsys):
    _, cfg_path, ext, tmp, _ = env
    code = main(["--config", str(cfg_path), "--no-db"], extractor=ext)
    out = capsys.readouterr().out
    assert code == 0
    assert "4" in out and "claim" in out
    assert "지어낸" not in out  # 문서 글자는 안 찍는다
    assert (tmp / "work" / "cite-idx-v1" / "index_report.json").exists()


def test_조각이_0개면_종료_1과_이유_한_줄(env, capsys):
    _, cfg_path, _, _, _ = env
    ext = FakeExtractor(
        {"KR100A.pdf": [PageText(page=1, lines=[])], "NPL_a.pdf": RuntimeError("x")}
    )
    code = main(["--config", str(cfg_path), "--no-db"], extractor=ext)
    assert code == 1
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and "0" in err[0]


def test_jsonl이_git에_들어갈_수_있는_경로면_종료_1(env, capsys):
    _, cfg_path, ext, tmp, _ = env
    out = tmp / "chunks.jsonl"  # tmp_path는 저장소 밖이라 git이 무시한다고 확인 못 함
    code = main(["--config", str(cfg_path), "--no-db", "--jsonl", str(out)], extractor=ext)
    assert code == 1
    assert not out.exists()
    assert ext.calls == 0  # 만들기 전에 거절


def test_jsonl이_git_밖_경로면_조각을_쓴다(env):
    _, cfg_path, ext, _, _ = env
    out = REPO / "work" / "cite_search" / "test_cite_index_dump.jsonl"
    ignored = subprocess.run(["git", "check-ignore", "-q", str(out)], cwd=REPO).returncode == 0
    assert ignored, "work/는 git 제외여야 한다"
    try:
        code = main(["--config", str(cfg_path), "--no-db", "--jsonl", str(out)], extractor=ext)
        assert code == 0
        rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 4
    finally:
        out.unlink(missing_ok=True)
