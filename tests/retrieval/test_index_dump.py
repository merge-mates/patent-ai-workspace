"""덤프 이름·revision 검사·CLI 인자 오류 (DB 없이). 기대값은 tasks.md m2-i2 task-3에서 가져온다."""

from pathlib import Path

import pytest

from patent_ai.db import index_dump
from patent_ai.db.index_dump import (
    IndexDumpError,
    RevisionMismatch,
    check_revision,
    dump_name,
    fixture_rows,
    main,
    parse_alembic_current,
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


def test_revision_옆_파일이_없으면_경고만_하고_성공(tmp_path, capsys):
    assert main(["check-revision", str(tmp_path / "없음.revision")]) == 0
    assert "경고" in capsys.readouterr().err


def test_revision_파일과_현재가_다르면_실패(tmp_path, monkeypatch, capsys):
    f = tmp_path / "x.revision"
    f.write_text("abc\n")
    monkeypatch.setattr(index_dump, "current_revision", lambda: "def")
    assert main(["check-revision", str(f)]) == 1
    assert capsys.readouterr().err.strip()


def test_revision_파일과_현재가_같으면_성공(tmp_path, monkeypatch):
    f = tmp_path / "x.revision"
    f.write_text("abc\n")
    monkeypatch.setattr(index_dump, "current_revision", lambda: "abc")
    assert main(["check-revision", str(f)]) == 0
