"""검색 색인 덤프 도구 (design.md 5-2, db/CLAUDE.md 검색 색인 절).

`python -m patent_ai.db.index_dump <하위 명령>`을 Makefile(index-dump·index-load)이 부른다.
  name <말뭉치>               DB 표의 가장 높은 색인 판으로 덤프 파일 이름을 찍는다
  current-revision            지금 DB의 Alembic revision을 찍는다 (.revision 파일에 쓸 값)
  check-revision <파일>       .revision 파일의 값과 지금 DB revision을 비교한다
  load-fixture <말뭉치> <jsonl>  손 확인용으로 fixture 조각을 그 말뭉치 표에 넣는다

db는 retrieval을 import하지 않는다(ADR 0003). 그래서 load-fixture는 JSONL을 여기서 직접 읽는다.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from patent_ai.db.models.chunks import CiteChunk, LawChunk
from patent_ai.settings import get_settings

_TABLES: dict[str, type[LawChunk] | type[CiteChunk]] = {"law": LawChunk, "cite": CiteChunk}


class IndexDumpError(ValueError):
    """덤프 이름·입력이 잘못됐다. 메시지는 한 줄."""


class RevisionMismatch(IndexDumpError):
    """덤프를 만든 DB와 지금 DB의 마이그레이션 revision이 다르다."""


def _check_corpus(corpus: str) -> None:
    if corpus not in _TABLES:
        raise IndexDumpError(f"말뭉치는 law 또는 cite여야 한다: {corpus!r}")


def dump_name(corpus: str, versions: list[str]) -> str:
    """덤프 파일 이름. 이름의 색인 판은 가장 높은 판이다 (숫자로 비교: v10 > v9)."""
    _check_corpus(corpus)
    if not versions:
        raise IndexDumpError(f"{corpus}_chunks 표에 색인 판이 없다 (빈 표는 덤프하지 않는다)")
    pattern = re.compile(rf"^{corpus}-idx-v([0-9]+)$")
    numbers = []
    for v in versions:
        m = pattern.match(v)
        if m is None:
            # 다른 말뭉치 판이 섞였거나 이름 규칙에 안 맞는 판
            raise IndexDumpError(f"{corpus} 표에 맞지 않는 색인 판: {v!r}")
        numbers.append(int(m.group(1)))
    return f"{corpus}-idx-v{max(numbers)}.dump"


def parse_alembic_current(text: str) -> str:
    """`alembic current` 출력에서 revision만 꺼낸다. 비어 있으면(마이그레이션 전) 오류."""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line.removesuffix("(head)").strip()
    raise IndexDumpError("alembic current 출력이 비었다. make db로 마이그레이션을 먼저 올린다")


def check_revision(dump_rev: str, current_rev: str) -> None:
    if dump_rev != current_rev:
        raise RevisionMismatch(
            f"덤프를 만든 DB revision {dump_rev}이 지금 DB {current_rev}과 다르다. "
            "make db로 마이그레이션을 맞춘 뒤 다시 한다"
        )


def current_revision() -> str:
    """지금 DB의 revision (alembic current 결과)."""
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "current"], capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise IndexDumpError("alembic current 실패: DB가 켜져 있는지 확인한다 (make db)")
    return parse_alembic_current(proc.stdout)


def _date(value: str | None) -> date | None:
    return None if value is None else date.fromisoformat(value)


def fixture_rows(corpus: str, text: str) -> list[LawChunk | CiteChunk]:
    """fixture JSONL을 그 말뭉치 표의 행으로 바꾼다 (retrieval.chunk_to_row와 같은 칸 규칙)."""
    _check_corpus(corpus)
    table = _TABLES[corpus]
    prefix = re.compile(rf"^{corpus}-idx-v[0-9]+$")
    rows: list[LawChunk | CiteChunk] = []
    for no, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        d = json.loads(line)
        loc, ed = d["location"], d["edition"]
        # 말뭉치와 색인 판 앞말, 판본 상태가 그 표와 맞는지 (표가 섞이면 막는다)
        if not prefix.match(d["index_version"]):
            raise IndexDumpError(
                f"{no}번째 줄 색인 판 {d['index_version']!r}이 {corpus}와 안 맞는다"
            )
        not_applicable = ed["status"] == "not_applicable"
        if (corpus == "law" and not_applicable) or (corpus == "cite" and not not_applicable):
            raise IndexDumpError(
                f"{no}번째 줄 판본 상태 {ed['status']!r}이 {corpus} 표와 안 맞는다"
            )
        rows.append(
            table(
                chunk_id=d["chunk_id"],
                index_version=d["index_version"],
                doc_id=d["doc_id"],
                chunk_kind=d["chunk_kind"],
                loc_kind=loc["kind"],
                loc_start=loc.get("start"),
                loc_end=loc.get("end"),
                loc_figures=list(loc.get("figures", [])),
                loc_claims=list(loc.get("claims", [])),
                loc_label=loc["label"],
                edition_status=ed["status"],
                edition_effective_from=_date(ed.get("effective_from")),
                edition_effective_to=_date(ed.get("effective_to")),
                edition_label=ed.get("label"),
                text=d["text"],
                embedding=d.get("embedding"),
            )
        )
    return rows


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        return _run(args)
    except IndexDumpError as e:
        return _fail(str(e))


def _run(args: list[str]) -> int:
    usage = (
        "쓰는 법: name <말뭉치> | current-revision | check-revision <파일> "
        "| load-fixture <말뭉치> <jsonl>"
    )
    if not args:
        return _fail(usage)
    cmd, rest = args[0], args[1:]

    if cmd == "name" and len(rest) == 1:
        _check_corpus(rest[0])
        table = _TABLES[rest[0]]
        with Session(create_engine(get_settings().database_url)) as s:
            versions = list(s.scalars(select(table.index_version).distinct()))
        print(dump_name(rest[0], versions))
        return 0

    if cmd == "current-revision" and not rest:
        print(current_revision())
        return 0

    if cmd == "check-revision" and len(rest) == 1:
        path = Path(rest[0])
        if not path.exists():
            # 옆 파일이 없으면 막지 않고 알리기만 한다 (기준 6, 있으면 좋음)
            print(f"경고: {path} 없음. revision 검사 없이 넣는다", file=sys.stderr)
            return 0
        check_revision(path.read_text(encoding="utf-8").strip(), current_revision())
        return 0

    if cmd == "load-fixture" and len(rest) == 2:
        corpus, jsonl = rest
        _check_corpus(corpus)
        if not Path(jsonl).exists():
            return _fail(f"파일이 없다: {jsonl}")
        rows = fixture_rows(corpus, Path(jsonl).read_text(encoding="utf-8"))
        if not rows:
            # 빈 파일이면 DB에 닿기 전에 멈춘다 (조용히 0개 넣고 성공하지 않게)
            return _fail(f"경고: {jsonl}에서 읽은 조각이 0개다. 아무것도 넣지 않는다")
        table = _TABLES[corpus]
        with Session(create_engine(get_settings().database_url)) as s:
            have = set(s.scalars(select(table.chunk_id)))
            new = [r for r in rows if r.chunk_id not in have]  # 같은 chunk_id는 건너뜀
            s.add_all(new)
            s.commit()
        print(f"{corpus}_chunks: {len(new)}개 넣음, {len(rows) - len(new)}개 건너뜀")
        return 0

    return _fail(usage)


if __name__ == "__main__":
    raise SystemExit(main())
