"""법령 색인 DB 넣기 테스트 (#66 task 4). 실제 DB 없이: 문장 모양과 지키는 선만 본다.

실제 DB에 넣는 것은 사람이 확인한 뒤 손으로 한 번 돌린다 (공유 DB, make test-db 안 씀).
"""

from datetime import date

import pytest
from sqlalchemy.dialects import postgresql

from patent_ai.retrieval.law_index_db import (
    IndexDbError,
    delete_statement,
    main,
    read_chunks_jsonl,
    replace_index,
)
from patent_ai.retrieval.repository import chunk_to_row
from patent_ai.retrieval.schemas import Chunk, Edition, Location

V = "law-idx-v1"


def _chunk(loc: int, version: str = V, status: str = "confirmed") -> Chunk:
    return Chunk(
        chunk_id=f"{version}:d:{loc}",
        index_version=version,
        doc_id="d",
        chunk_kind="article",
        location=Location(kind="article", start=loc, end=loc, label=str(loc)),
        edition=Edition(status=status, effective_from=date(2020, 3, 11)),
        text="가나",
    )


class _Untouchable:
    """건드리면 실패하는 세션: 검사에서 먼저 멈췄는지 본다."""

    def __getattr__(self, name):
        raise AssertionError(f"검사 전에 DB를 건드렸다: {name}")


class _Recorder:
    """부른 순서를 적는 가짜 세션."""

    def __init__(self, count_after: int, existing: list[Chunk] | None = None, corpus: str = "law"):
        self.calls: list[str] = []
        self.added = 0
        self._count = count_after
        # DB에 이미 있는 그 판 줄 (없으면 빈 표)
        self._existing = [chunk_to_row(corpus, c) for c in existing or []]

    def scalars(self, stmt):
        self.calls.append("read")
        return self._existing

    def begin(self):
        rec = self

        class _Tx:
            def __enter__(self):
                rec.calls.append("begin")

            def __exit__(self, exc_type, *a):
                rec.calls.append("rollback" if exc_type else "commit")
                return False

        return _Tx()

    def execute(self, stmt):
        # 실제로 넘긴 문장이 law_chunks의 그 판 줄만 지우는지 적어 둔다
        sql = stmt.compile(dialect=postgresql.dialect())
        self.sql = (str(sql), list(sql.params.values()))
        self.calls.append("delete")

    def add_all(self, rows):
        rows = list(rows)
        self.added += len(rows)
        self.calls.append("add")

    def scalar(self, stmt):
        self.calls.append("count")
        return self._count


def test_지우는_문장은_law_chunks_이번_판만():
    sql = delete_statement("law", V).compile(dialect=postgresql.dialect())
    text = str(sql)
    assert text.startswith("DELETE FROM law_chunks WHERE law_chunks.index_version =")
    assert list(sql.params.values()) == [V]
    assert "cite_chunks" not in text


@pytest.mark.parametrize("bad", ["cite-idx-v1", "law-idx-v1; DROP", "", "law-idx"])
def test_법령_색인_판_이름이_아니면_DB_전에_멈춘다(bad):
    with pytest.raises(IndexDbError):
        replace_index(_Untouchable(), [_chunk(1)], "law", bad)


def test_다른_판_조각이_섞이면_DB_전에_멈춘다():
    with pytest.raises(IndexDbError):
        replace_index(_Untouchable(), [_chunk(1), _chunk(2, "law-idx-v2")], "law", V)


def test_판본_not_applicable_조각은_법령_표에_못_넣는다():
    with pytest.raises(IndexDbError):
        replace_index(_Untouchable(), [_chunk(1, status="not_applicable")], "law", V)


def test_조각이_0개면_DB_전에_멈춘다():
    with pytest.raises(IndexDbError):
        replace_index(_Untouchable(), [], "law", V)


def test_한_묶음_안에서_지우고_넣고_센다():
    s = _Recorder(count_after=2)
    assert replace_index(s, [_chunk(1), _chunk(2)], "law", V) == 2
    assert s.calls == ["begin", "read", "delete", "add", "count", "commit"]
    assert s.added == 2
    text, params = s.sql
    assert text.startswith("DELETE FROM law_chunks WHERE law_chunks.index_version =")
    assert params == [V]


def test_같은_내용이면_다시_넣는다():
    same = [_chunk(1), _chunk(2)]
    s = _Recorder(count_after=2, existing=same)
    assert replace_index(s, [_chunk(2), _chunk(1)], "law", V) == 2  # 순서만 달라도 같은 내용
    assert "delete" in s.calls


def test_같은_판_이름인데_내용이_다르면_지우지_않고_멈춘다():
    old = [_chunk(1), _chunk(2)]
    changed = [_chunk(1), _chunk(2).model_copy(update={"text": "바뀐 글"})]
    s = _Recorder(count_after=2, existing=old)
    with pytest.raises(IndexDbError, match="새 판"):
        replace_index(s, changed, "law", V)
    assert "delete" not in s.calls and s.calls[-1] == "rollback"


def test_JSONL은_판으로_거르지_않고_줄을_다_읽어_섞인_판을_잡는다(tmp_path):
    # 명령 경로: 다른 판 줄이 섞인 파일이면 말없이 빠지지 않고 검사에서 멈춰야 한다
    path = tmp_path / "mixed.jsonl"
    rows = [_chunk(1), _chunk(2, "law-idx-v2"), _chunk(3, "law-idx-v2")]
    path.write_text("".join(c.model_dump_json() + "\n" for c in rows), encoding="utf-8")
    chunks = read_chunks_jsonl(path, "law")
    assert len(chunks) == 3
    with pytest.raises(IndexDbError):
        replace_index(_Untouchable(), chunks, "law", V)


def test_넣은_수가_다르면_되돌린다():
    s = _Recorder(count_after=1)
    with pytest.raises(IndexDbError):
        replace_index(s, [_chunk(1), _chunk(2)], "law", V)
    assert s.calls[-1] == "rollback"


# ---- cite 말뭉치 (#67 m2-i2 task-2) ----

CV = "cite-idx-v2"


def _cite(n: int, version: str = CV, status: str = "not_applicable") -> Chunk:
    return Chunk(
        chunk_id=f"{version}:KRTEST1A:pg{n}",
        index_version=version,
        doc_id="KRTEST1A",
        chunk_kind="body",
        location=Location(kind="page", start=n, end=n, label=f"{n}쪽"),
        edition=Edition(status=status),
        text="지어낸 글",
        embedding=[0.1, 0.2],
    )


def test_cite_지우는_문장은_cite_chunks_이번_판만():
    sql = delete_statement("cite", CV).compile(dialect=postgresql.dialect())
    assert str(sql).startswith("DELETE FROM cite_chunks WHERE cite_chunks.index_version =")
    assert list(sql.params.values()) == [CV]


def test_cite_한_묶음_안에서_지우고_넣고_센다():
    s = _Recorder(count_after=2, corpus="cite")
    assert replace_index(s, [_cite(1), _cite(2)], "cite", CV) == 2
    assert s.calls == ["begin", "read", "delete", "add", "count", "commit"]
    assert s.sql[0].startswith("DELETE FROM cite_chunks")


def test_cite_조각이_0개면_DB_전에_멈춘다():
    with pytest.raises(IndexDbError):
        replace_index(_Untouchable(), [], "cite", CV)


def test_cite_말뭉치에_law_판_이름은_DB_전에_멈춘다():
    with pytest.raises(IndexDbError):
        replace_index(_Untouchable(), [_cite(1, "law-idx-v2")], "cite", "law-idx-v2")


def test_cite_조각에_판본이_있으면_DB_전에_멈춘다():
    with pytest.raises(IndexDbError):
        replace_index(_Untouchable(), [_cite(1, status="confirmed")], "cite", CV)


def test_cite_판이_섞이면_DB_전에_멈춘다():
    with pytest.raises(IndexDbError):
        replace_index(_Untouchable(), [_cite(1), _cite(2, "cite-idx-v1")], "cite", CV)


def test_cite_같은_판_이름인데_내용이_다르면_멈춘다():
    old = [_cite(1)]
    s = _Recorder(count_after=1, existing=old, corpus="cite")
    with pytest.raises(IndexDbError, match="새 판"):
        replace_index(s, [_cite(1).model_copy(update={"text": "바뀜"})], "cite", CV)
    assert "delete" not in s.calls


def test_명령은_깨진_JSONL이면_traceback_없이_1로_끝난다(tmp_path, caplog):
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{깨짐\n", encoding="utf-8")
    argv = ["--corpus", "cite", "--jsonl", str(bad), "--index-version", CV]
    assert main(argv) == 1
    errs = [r for r in caplog.records if r.levelname == "ERROR"]
    assert errs and "bad.jsonl" in errs[0].getMessage()  # 파일 경로가 든 이유 한 줄


def test_명령은_말뭉치와_안_맞는_파일이면_1로_끝난다(tmp_path):
    f = tmp_path / "c.jsonl"
    f.write_text(_cite(1).model_dump_json() + "\n", encoding="utf-8")
    # cite 조각 파일을 law로 읽으면 판 앞말이 안 맞아 막힌다
    assert main(["--jsonl", str(f), "--index-version", "law-idx-v1"]) == 1


def test_us_줄_판은_DB를_건드리기_전에_멈춘다():
    # DB CHECK가 v 줄만 받아서, 세션을 열기 전에 분명한 오류로 멈춰야 한다
    with pytest.raises(IndexDbError, match="us 줄"):
        replace_index(_Untouchable(), [_chunk(1, "cite-idx-us1")], "cite", "cite-idx-us1")
