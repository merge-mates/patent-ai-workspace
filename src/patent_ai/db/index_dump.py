"""검색 색인 덤프 도구 (design.md 5-2, db/CLAUDE.md 검색 색인 절).

`python -m patent_ai.db.index_dump <하위 명령>`을 Makefile(index-dump·index-load)이 부른다.
  name <말뭉치>               DB 표의 가장 높은 색인 판으로 덤프 파일 이름을 찍는다
  current-revision            지금 DB의 Alembic revision을 찍는다 (.revision 파일에 쓸 값)
  fingerprint <말뭉치>        DB 표의 색인 판마다 지문을 JSON으로 찍는다 (.fingerprint.json에 쓸 값)
  check-before-load <덤프>    넣기 전: 옆 .revision·.fingerprint.json이 있고 revision이 같은지
  check-after-load <덤프>     넣은 뒤: DB를 다시 세어 지문이 옆 파일과 같은지
  load-fixture <말뭉치> <jsonl>  손 확인용으로 fixture 조각을 그 말뭉치 표에 넣는다

db는 retrieval을 import하지 않는다(ADR 0003). 그래서 load-fixture는 JSONL을 여기서 직접 읽는다.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from patent_ai.db.models.chunks import (
    CiteChunk,
    LawChunk,
    check_cite_chunk_meta,
    check_law_chunk,
)
from patent_ai.index_version import corpus_of, is_index_version, version_number
from patent_ai.settings import get_settings

_TABLES: dict[str, type[LawChunk] | type[CiteChunk]] = {"law": LawChunk, "cite": CiteChunk}


class IndexDumpError(ValueError):
    """덤프 이름·입력이 잘못됐다. 메시지는 한 줄."""


class RevisionMismatch(IndexDumpError):
    """덤프를 만든 DB와 지금 DB의 마이그레이션 revision이 다르다."""


class FingerprintMismatch(IndexDumpError):
    """넣은 색인의 조각 수·chunk_id 목록이 덤프를 만든 쪽과 다르다 (덜 받았거나 다른 덤프)."""


def _check_corpus(corpus: str) -> None:
    if corpus not in _TABLES:
        raise IndexDumpError(f"말뭉치는 law 또는 cite여야 한다: {corpus!r}")


def dump_name(corpus: str, versions: list[str]) -> str:
    """덤프 파일 이름. 이름의 색인 판은 가장 높은 판이다 (숫자로 비교: v10 > v9)."""
    _check_corpus(corpus)
    if not versions:
        raise IndexDumpError(f"{corpus}_chunks 표에 색인 판이 없다 (빈 표는 덤프하지 않는다)")
    numbers = []
    for v in versions:
        n = version_number(corpus, v)
        if n is None:
            # 다른 말뭉치 판이 섞였거나 이름 규칙에 안 맞는 판
            raise IndexDumpError(f"{corpus} 표에 맞지 않는 색인 판: {v!r}")
        numbers.append(n)
    return f"{corpus}-idx-v{max(numbers)}.dump"


# ---- 색인 지문 (design 5-2) ----
# 색인 판 이름만 같고 내용이 다른 경우(같은 이름으로 다시 만듦, 덜 받음)를 잡는다.
# 채점기 scores.json의 index_fingerprint도 같은 계산이다 (#101).
def index_fingerprint(chunk_ids: Iterable[str]) -> dict[str, int | str]:
    """조각 수 + chunk_id를 정렬해 줄바꿈으로 이은 글자의 sha256."""
    ids = sorted(chunk_ids)
    digest = hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()
    return {"chunks": len(ids), "chunk_ids_sha256": digest}


def fingerprints_by_version(rows: Iterable[tuple[str, str]]) -> dict[str, dict[str, int | str]]:
    """(index_version, chunk_id) 줄들 → 색인 판마다 지문."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for version, chunk_id in rows:
        grouped[version].append(chunk_id)
    return {v: index_fingerprint(ids) for v, ids in sorted(grouped.items())}


def compare_fingerprints(expected: dict, actual: dict) -> None:
    """색인 판 목록과 판마다 지문이 같아야 한다. 다르면 어느 판이 어떻게 다른지 한 줄로."""
    diffs = []
    for v in sorted(set(expected) | set(actual)):
        e, a = expected.get(v), actual.get(v)
        if e is None:
            diffs.append(f"{v}: 덤프에 없던 판이 DB에 있다")
        elif a is None:
            diffs.append(f"{v}: DB에 없다 (덤프에는 조각 {e['chunks']}개)")
        elif e != a:
            diffs.append(f"{v}: 조각 {e['chunks']}개 기대, DB {a['chunks']}개 (목록 해시 다름)")
    if diffs:
        raise FingerprintMismatch(
            "넣은 색인이 덤프를 만든 쪽과 다르다: "
            + "; ".join(diffs)
            + ". 덤프를 다시 받아 make index-load를 다시 한다"
        )


def sibling_paths(dump: Path) -> tuple[Path, Path]:
    """덤프 옆 파일 두 개: <이름>.revision, <이름>.fingerprint.json."""
    stem = dump.with_suffix("")
    return stem.with_name(stem.name + ".revision"), stem.with_name(stem.name + ".fingerprint.json")


def _corpus_of_dump(dump: Path) -> str:
    corpus = corpus_of(dump.name.removesuffix(".dump")) if dump.name.endswith(".dump") else None
    if corpus is None:
        raise IndexDumpError(f"덤프 이름이 <말뭉치>-idx-v<n>.dump 꼴이 아니다: {dump.name}")
    return corpus


def read_fingerprint_file(path: Path, corpus: str) -> dict:
    """옆 지문 파일을 읽는다. 없거나 모양이 틀리거나 말뭉치가 다르면 멈춘다."""
    if not path.exists():
        # make index-dump는 늘 같이 만든다. 없으면 덜 받은 것이다
        raise IndexDumpError(f"{path} 없음. 덤프와 옆 파일 셋을 같이 받는다 (덜 받은 덤프)")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        versions = data["versions"]
        file_corpus = data["corpus"]
    except (ValueError, KeyError, TypeError) as e:
        raise IndexDumpError(f"{path} 모양이 틀렸다: {e}") from e
    if file_corpus != corpus:
        raise IndexDumpError(f"{path}의 말뭉치 {file_corpus!r}이 덤프 {corpus!r}와 다르다")
    if not versions:
        raise IndexDumpError(f"{path}에 색인 판이 없다")
    return versions


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
    rows: list[LawChunk | CiteChunk] = []
    for no, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        d = json.loads(line)
        loc, ed = d["location"], d["edition"]
        # 말뭉치와 색인 판 앞말, 판본 상태가 그 표와 맞는지 (표가 섞이면 막는다)
        if not is_index_version(corpus, d["index_version"]):
            raise IndexDumpError(
                f"{no}번째 줄 색인 판 {d['index_version']!r}이 {corpus}와 안 맞는다"
            )
        not_applicable = ed["status"] == "not_applicable"
        if corpus == "cite" and not not_applicable:
            raise IndexDumpError(
                f"{no}번째 줄 판본 상태 {ed['status']!r}이 {corpus} 표와 안 맞는다"
            )
        # 법령 표 규칙(not_applicable은 판례·심결만 등)은 넣기·저장소와 같은 함수 하나로 본다
        if corpus == "law":
            reason = check_law_chunk(
                d["chunk_kind"],
                ed["status"],
                d.get("source_kind") or "statute",
                d.get("decided_on"),
                d.get("speaker"),
            )
        else:
            reason = check_cite_chunk_meta(
                d.get("source_kind"), d.get("decided_on"), d.get("speaker"), d.get("attrs")
            )
        if reason:
            raise IndexDumpError(f"{no}번째 줄 {reason}")
        # law 표 새 칸 넷 (retrieval.chunk_to_row·fill_law_defaults와 같은 규칙: 없으면 statute)
        extra = {}
        if corpus == "law":
            extra = {
                "source_kind": d.get("source_kind") or "statute",
                "decided_on": _date(d.get("decided_on")),
                "speaker": d.get("speaker"),
                "attrs": d.get("attrs"),
            }
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
                **extra,
            )
        )
    return rows


def _db_rows(corpus: str) -> list[tuple[str, str]]:
    """DB 표의 (index_version, chunk_id) 전부. 지문 계산용."""
    table = _TABLES[corpus]
    with Session(create_engine(get_settings().database_url)) as s:
        return [(v, c) for v, c in s.execute(select(table.index_version, table.chunk_id))]


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
        "쓰는 법: name <말뭉치> | current-revision | fingerprint <말뭉치> "
        "| check-before-load <덤프> | check-after-load <덤프> | load-fixture <말뭉치> <jsonl>"
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

    if cmd == "fingerprint" and len(rest) == 1:
        _check_corpus(rest[0])
        versions = fingerprints_by_version(_db_rows(rest[0]))
        if not versions:
            return _fail(f"{rest[0]}_chunks 표가 비었다 (빈 표는 덤프하지 않는다)")
        print(json.dumps({"corpus": rest[0], "versions": versions}, ensure_ascii=False, indent=2))
        return 0

    if cmd == "check-before-load" and len(rest) == 1:
        dump = Path(rest[0])
        corpus = _corpus_of_dump(dump)
        rev_path, fp_path = sibling_paths(dump)
        # 옆 파일 둘 중 하나라도 없으면 덜 받은 것이니 넣기 전에 멈춘다
        if not rev_path.exists():
            return _fail(f"{rev_path} 없음. 덤프와 옆 파일 셋을 같이 받는다 (덜 받은 덤프)")
        read_fingerprint_file(fp_path, corpus)
        check_revision(rev_path.read_text(encoding="utf-8").strip(), current_revision())
        return 0

    if cmd == "check-after-load" and len(rest) == 1:
        dump = Path(rest[0])
        corpus = _corpus_of_dump(dump)
        expected = read_fingerprint_file(sibling_paths(dump)[1], corpus)
        # 넣은 뒤 DB를 다시 세어 덤프를 만든 쪽과 같은지 본다
        compare_fingerprints(expected, fingerprints_by_version(_db_rows(corpus)))
        print(f"{corpus}_chunks: 지문 같음 ({', '.join(sorted(expected))})")
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
