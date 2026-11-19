"""법령 색인 DB 넣기 테스트 (#66 task 4). 실제 DB 없이: 문장 모양과 지키는 선만 본다.

실제 DB에 넣는 것은 사람이 확인한 뒤 손으로 한 번 돌린다 (공유 DB, make test-db 안 씀).
"""

from datetime import date

import pytest
from sqlalchemy.dialects import postgresql

from patent_ai.retrieval.law_index_db import LawIndexDbError, delete_statement, replace_law_index
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

    def __init__(self, count_after: int):
        self.calls: list[str] = []
        self.added = 0
        self._count = count_after

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
        self.calls.append("delete")

    def add_all(self, rows):
        rows = list(rows)
        self.added += len(rows)
        self.calls.append("add")

    def scalar(self, stmt):
        self.calls.append("count")
        return self._count


def test_지우는_문장은_law_chunks_이번_판만():
    sql = delete_statement(V).compile(dialect=postgresql.dialect())
    text = str(sql)
    assert text.startswith("DELETE FROM law_chunks WHERE law_chunks.index_version =")
    assert list(sql.params.values()) == [V]
    assert "cite_chunks" not in text


@pytest.mark.parametrize("bad", ["cite-idx-v1", "law-idx-v1; DROP", "", "law-idx"])
def test_법령_색인_판_이름이_아니면_DB_전에_멈춘다(bad):
    with pytest.raises(LawIndexDbError):
        replace_law_index(_Untouchable(), [_chunk(1)], bad)


def test_다른_판_조각이_섞이면_DB_전에_멈춘다():
    with pytest.raises(LawIndexDbError):
        replace_law_index(_Untouchable(), [_chunk(1), _chunk(2, "law-idx-v2")], V)


def test_판본_not_applicable_조각은_법령_표에_못_넣는다():
    with pytest.raises(LawIndexDbError):
        replace_law_index(_Untouchable(), [_chunk(1, status="not_applicable")], V)


def test_조각이_0개면_DB_전에_멈춘다():
    with pytest.raises(LawIndexDbError):
        replace_law_index(_Untouchable(), [], V)


def test_한_묶음_안에서_지우고_넣고_센다():
    s = _Recorder(count_after=2)
    assert replace_law_index(s, [_chunk(1), _chunk(2)], V) == 2
    assert s.calls == ["begin", "delete", "add", "count", "commit"]
    assert s.added == 2


def test_넣은_수가_다르면_되돌린다():
    s = _Recorder(count_after=1)
    with pytest.raises(LawIndexDbError):
        replace_law_index(s, [_chunk(1), _chunk(2)], V)
    assert s.calls[-1] == "rollback"
