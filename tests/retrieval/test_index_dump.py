"""덤프 이름·revision 검사·CLI 인자 오류 (DB 없이). 기대값은 tasks.md m2-i2 task-3에서 가져온다."""

import hashlib
import json
from pathlib import Path

import pytest

from patent_ai.db import index_dump
from patent_ai.db.index_dump import (
    FingerprintMismatch,
    IndexDumpError,
    RevisionMismatch,
    check_revision,
    compare_fingerprints,
    dump_name,
    fingerprints_by_version,
    fixture_rows,
    index_fingerprint,
    main,
    parse_alembic_current,
    sibling_paths,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "retrieval"


# ---- dump_name ----
def test_가장_높은_색인_판으로_이름을_짓는다():
    assert dump_name("cite", ["cite-idx-v1", "cite-idx-v2"]) == "cite-idx-v2.dump"


def test_색인_판은_숫자로_비교한다():
    assert dump_name("law", ["law-idx-v9", "law-idx-v10"]) == "law-idx-v10.dump"


def test_색인_판이_없으면_오류():
    with pytest.raises(IndexDumpError):
        dump_name("cite", [])


def test_말뭉치가_law도_cite도_아니면_오류():
    with pytest.raises(IndexDumpError):
        dump_name("other", ["other-idx-v1"])


def test_다른_말뭉치_색인_판이_섞이면_오류():
    with pytest.raises(IndexDumpError):
        dump_name("law", ["law-idx-v1", "cite-idx-v1"])


# ---- alembic current ----
def test_head_표시를_뗀다():
    assert parse_alembic_current("abc123 (head)\n") == "abc123"


def test_head_표시가_없어도_읽는다():
    assert parse_alembic_current("abc123") == "abc123"


@pytest.mark.parametrize("text", ["", "  \n"])
def test_alembic_출력이_비면_오류(text):
    with pytest.raises(IndexDumpError):
        parse_alembic_current(text)


def test_revision이_다르면_RevisionMismatch():
    check_revision("abc", "abc")  # 같으면 조용히 통과
    with pytest.raises(RevisionMismatch):
        check_revision("abc", "def")


# ---- load-fixture 행 만들기 ----
def test_fixture_줄이_그_말뭉치_표_행이_된다():
    rows = fixture_rows("cite", (FIXTURES / "chunks_cite.jsonl").read_text(encoding="utf-8"))
    assert rows
    assert {type(r).__name__ for r in rows} == {"CiteChunk"}
    assert all(r.index_version == "cite-idx-v1" for r in rows)


def test_law_표에_cite_줄을_넣으면_오류():
    with pytest.raises(IndexDumpError):
        fixture_rows("law", (FIXTURES / "chunks_cite.jsonl").read_text(encoding="utf-8"))


# ---- CLI 인자 오류 (DB를 열기 전에 끝난다) ----
@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["모르는명령"],
        ["name", "other"],
        ["name"],
        ["load-fixture", "other", str(FIXTURES / "chunks_cite.jsonl")],
        ["load-fixture", "cite", "없는파일.jsonl"],
    ],
)
def test_인자가_틀리면_종료_코드_1(argv, capsys):
    assert main(argv) == 1
    assert capsys.readouterr().err.strip()  # 이유 한 줄


# ---- 색인 지문 (design 5-2) ----
def test_지문은_조각_수와_정렬한_chunk_id_목록_해시():
    # 기대값: 정렬 뒤 줄바꿈으로 이은 글자의 sha256. #101 채점기 지문과 같은 계산이어야 한다
    fp = index_fingerprint(["b", "a"])
    assert fp == {"chunks": 2, "chunk_ids_sha256": hashlib.sha256(b"a\nb").hexdigest()}
    assert index_fingerprint(["a", "b"]) == fp  # 순서가 달라도 같다


def test_지문은_색인_판마다_따로():
    rows = [("cite-idx-v2", "x"), ("cite-idx-v1", "b"), ("cite-idx-v1", "a")]
    fps = fingerprints_by_version(rows)
    assert list(fps) == ["cite-idx-v1", "cite-idx-v2"]
    assert fps["cite-idx-v1"] == index_fingerprint(["a", "b"])
    assert fps["cite-idx-v2"]["chunks"] == 1


def test_지문이_같으면_통과_다르면_FingerprintMismatch():
    e = fingerprints_by_version([("cite-idx-v1", "a"), ("cite-idx-v1", "b")])
    compare_fingerprints(e, dict(e))
    # 한 조각 덜 받음
    with pytest.raises(FingerprintMismatch, match="cite-idx-v1.*2개 기대.*1개"):
        compare_fingerprints(e, fingerprints_by_version([("cite-idx-v1", "a")]))
    # 수는 같은데 다른 조각 (같은 이름으로 다시 만듦)
    other = fingerprints_by_version([("cite-idx-v1", "a"), ("cite-idx-v1", "c")])
    with pytest.raises(FingerprintMismatch):
        compare_fingerprints(e, other)
    # 판이 없거나 더 있음
    with pytest.raises(FingerprintMismatch, match="DB에 없다"):
        compare_fingerprints(e, {})
    with pytest.raises(FingerprintMismatch, match="덤프에 없던"):
        compare_fingerprints(e, {**e, "cite-idx-v2": index_fingerprint(["z"])})


def test_옆_파일_이름():
    rev, fp = sibling_paths(Path("data/index/law-idx-v1.dump"))
    assert rev == Path("data/index/law-idx-v1.revision")
    assert fp == Path("data/index/law-idx-v1.fingerprint.json")


# ---- check-before-load / check-after-load (DB 대신 monkeypatch) ----
def _dump_set(tmp_path, *, rev="abc", fp=True, rows=(("cite-idx-v1", "a"),)):
    dump = tmp_path / "cite-idx-v1.dump"
    dump.write_bytes(b"x")
    rev_path, fp_path = sibling_paths(dump)
    if rev is not None:
        rev_path.write_text(rev + "\n")
    if fp:
        data = {"corpus": "cite", "versions": fingerprints_by_version(rows)}
        fp_path.write_text(json.dumps(data))
    return dump


def test_넣기_전_옆_파일이_다_있고_revision이_같으면_성공(tmp_path, monkeypatch):
    monkeypatch.setattr(index_dump, "current_revision", lambda: "abc")
    assert main(["check-before-load", str(_dump_set(tmp_path))]) == 0


def test_넣기_전_revision_파일이_없으면_멈춤(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(index_dump, "current_revision", lambda: "abc")
    assert main(["check-before-load", str(_dump_set(tmp_path, rev=None))]) == 1
    assert ".revision 없음" in capsys.readouterr().err


def test_넣기_전_지문_파일이_없으면_멈춤(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(index_dump, "current_revision", lambda: "abc")
    assert main(["check-before-load", str(_dump_set(tmp_path, fp=False))]) == 1
    assert "fingerprint.json 없음" in capsys.readouterr().err


def test_넣기_전_revision이_다르면_멈춤(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(index_dump, "current_revision", lambda: "def")
    assert main(["check-before-load", str(_dump_set(tmp_path))]) == 1
    assert capsys.readouterr().err.strip()


def test_지문_파일_말뭉치가_덤프와_다르면_멈춤(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(index_dump, "current_revision", lambda: "abc")
    dump = _dump_set(tmp_path)
    sibling_paths(dump)[1].write_text(json.dumps({"corpus": "law", "versions": {"x": {}}}))
    assert main(["check-before-load", str(dump)]) == 1
    assert "말뭉치" in capsys.readouterr().err


def test_덤프_이름이_규칙에_안_맞으면_멈춤(tmp_path):
    bad = tmp_path / "idx-v1.dump"
    bad.write_bytes(b"x")
    assert main(["check-before-load", str(bad)]) == 1


def test_넣은_뒤_다시_센_지문이_같으면_성공(tmp_path, monkeypatch, capsys):
    rows = [("cite-idx-v1", "a"), ("cite-idx-v1", "b")]
    dump = _dump_set(tmp_path, rows=rows)
    monkeypatch.setattr(index_dump, "_db_rows", lambda corpus: list(rows))
    assert main(["check-after-load", str(dump)]) == 0
    assert "지문 같음" in capsys.readouterr().out


def test_넣은_뒤_조각이_덜_들어갔으면_종료_1(tmp_path, monkeypatch, capsys):
    dump = _dump_set(tmp_path, rows=[("cite-idx-v1", "a"), ("cite-idx-v1", "b")])
    monkeypatch.setattr(index_dump, "_db_rows", lambda corpus: [("cite-idx-v1", "a")])
    assert main(["check-after-load", str(dump)]) == 1
    assert "다르다" in capsys.readouterr().err


def test_빈_표는_지문을_찍지_않고_종료_1(monkeypatch):
    monkeypatch.setattr(index_dump, "_db_rows", lambda corpus: [])
    assert main(["fingerprint", "cite"]) == 1


def test_지문_명령은_말뭉치와_판별_지문을_JSON으로(monkeypatch, capsys):
    monkeypatch.setattr(index_dump, "_db_rows", lambda corpus: [("cite-idx-v1", "a")])
    assert main(["fingerprint", "cite"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"corpus": "cite", "versions": {"cite-idx-v1": index_fingerprint(["a"])}}


# ---- load-fixture 빈 파일 ----
def test_빈_fixture는_경고하고_DB에_닿기_전에_종료_1(tmp_path, monkeypatch, capsys):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n", encoding="utf-8")

    def no_db(*a, **k):
        raise AssertionError("DB에 닿으면 안 된다")

    monkeypatch.setattr(index_dump, "create_engine", no_db)
    assert main(["load-fixture", "cite", str(empty)]) == 1
    assert "0개" in capsys.readouterr().err
