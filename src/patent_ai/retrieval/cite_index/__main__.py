"""색인 명령: PDF 폴더 → 쪽 글자 → 머리말·꼬리말 빼기 → 조각 → cite_chunks + 보고 (design 2절).

문서 글자는 어디에도 찍지 않는다. 보고에는 숫자와 파일 이름·이유만 둔다.
"""

import argparse
import hashlib
import json
import logging
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from patent_ai.db.models.chunks import CiteChunk
from patent_ai.retrieval.cite_index.chunker import ChunkingConfig, chunk_document
from patent_ai.retrieval.cite_index.header_footer import strip_repeated
from patent_ai.retrieval.cite_index.pages import PageExtractor, PdfplumberExtractor
from patent_ai.retrieval.repository import chunk_to_row
from patent_ai.retrieval.schemas import Chunk
from patent_ai.settings import get_settings

log = logging.getLogger("patent_ai.cite_index")

REPO_ROOT = Path(__file__).resolve().parents[4]
# 한국 공보 파일 이름은 그대로 doc_id (KR10…A, KR10…B1 등)
_KR_STEM = re.compile(r"^KR\d+[AB]\d?$")


@dataclass
class IndexReport:
    index_version: str
    docs: dict[str, dict] = field(default_factory=dict)
    skipped: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        by_kind: Counter = Counter()
        for d in self.docs.values():
            by_kind.update(d["chunks"])
        return {
            "index_version": self.index_version,
            "docs": self.docs,
            "skipped": self.skipped,
            "warnings": self.warnings,
            "totals": {
                "docs": len(self.docs),
                "chunks": sum(by_kind.values()),
                "chunks_by_kind": dict(by_kind),
                "removed_lines": sum(d["removed_lines"] for d in self.docs.values()),
                "skipped": len(self.skipped),
            },
        }


def _resolve(path: str) -> Path:
    # 상대 경로는 저장소 루트 기준
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


def _chunking_config(cfg: dict) -> ChunkingConfig:
    c = cfg["chunking"]
    return ChunkingConfig(
        claims_heading=re.compile(c["claims_heading"]),
        abstract_heading=re.compile(c["abstract_heading"]),
        rep_figure=re.compile(c["rep_figure"]),
        figdesc_heading=re.compile(c["figdesc_heading"]),
        section_headings=[re.compile(p) for p in c["section_headings"]],
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _list_pdfs(raw_root: Path) -> list[Path]:
    # _meta 폴더와 PDF 아닌 파일은 빼고, (파일 이름, 폴더) 순으로 정렬
    pdfs = [
        p
        for p in raw_root.rglob("*")
        if p.is_file()
        and p.suffix.lower() == ".pdf"
        and not any(part == "_meta" for part in p.relative_to(raw_root).parts)
    ]
    return sorted(pdfs, key=lambda p: (p.name, str(p.parent)))


def build_index(cfg: dict, extractor: PageExtractor) -> tuple[list[Chunk], IndexReport]:
    iv = cfg["index_version"]
    hf = cfg["header_footer"]
    chunking = _chunking_config(cfg)
    table_path = _resolve(cfg["doc_id_table"])
    table = yaml.safe_load(table_path.read_text(encoding="utf-8")) if table_path.exists() else {}
    table = table or {}
    id_table: dict[str, str] = table.get("doc_ids") or {}
    skip_stems = set(table.get("skip") or [])

    report = IndexReport(index_version=iv)
    chunks: list[Chunk] = []
    seen_sha: dict[str, str] = {}  # doc_id -> 처음 본 파일의 sha256
    skipped_stems: set[str] = set()

    def skip(stem: str, reason: str) -> None:
        if stem not in skipped_stems:  # 사건 폴더마다 있어도 한 번만 적는다
            skipped_stems.add(stem)
            report.skipped.append({"file": stem, "reason": reason})

    for pdf in _list_pdfs(_resolve(cfg["raw_root"])):
        stem = pdf.stem
        if stem in skip_stems:
            skip(stem, "skip 표")
            continue
        if stem in id_table:
            doc_id = id_table[stem]
        elif _KR_STEM.match(stem):
            doc_id = stem
        else:
            log.warning("표에 없는 PDF를 건너뜀: %s", stem)
            skip(stem, "표에 없는 파일 이름")
            continue

        sha = _sha256(pdf)
        if doc_id in seen_sha:
            # 같은 공보가 다른 사건 폴더에 또 있음: 한 번만 색인하고 내용이 다르면 알린다
            if seen_sha[doc_id] != sha:
                msg = f"같은 doc_id인데 파일 sha256이 다름: {doc_id} ({pdf.parent.name})"
                log.warning(msg)
                report.warnings.append(msg)
            continue
        seen_sha[doc_id] = sha

        try:
            pages = extractor.extract(pdf)
        except Exception as e:  # noqa: BLE001 한 문헌의 오류가 전체를 멈추지 않게
            reason = f"추출 오류: {type(e).__name__}: {e}"
            log.warning("건너뜀 %s: %s", stem, reason)
            skip(stem, reason)
            continue

        stripped, removed = strip_repeated(
            pages, hf["scan_lines"], hf["min_page_ratio"], hf.get("keep_patterns", [])
        )
        doc_chunks, warns = chunk_document(doc_id, stripped, iv, chunking)
        for w in warns:
            log.warning(w)
        chunks.extend(doc_chunks)
        report.docs[doc_id] = {
            "pages": len(pages),
            "chunks": dict(Counter(c.chunk_kind for c in doc_chunks)),
            "removed_lines": removed,
            "warnings": len(warns),
        }

    out = _resolve(cfg["report_dir"]) / iv / "index_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return chunks, report


def write_index(session: Session, chunks: list[Chunk]) -> None:
    """같은 index_version 줄을 지우고 새로 넣는다 (한 트랜잭션: 실패하면 옛 줄 그대로)."""
    versions = {c.index_version for c in chunks}
    try:
        for v in versions:
            session.execute(delete(CiteChunk).where(CiteChunk.index_version == v))
        session.add_all([chunk_to_row("cite", c) for c in chunks])
        session.commit()
    except Exception:
        session.rollback()
        raise


def _git_ignored(path: Path) -> bool:
    # 저장소 밖이거나 git이 무시하지 않는 경로는 커밋될 수 있어 거절한다
    r = subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=REPO_ROOT, capture_output=True)
    return r.returncode == 0


def main(argv: list[str] | None = None, extractor: PageExtractor | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cite_index")
    ap.add_argument("--config", required=True)
    ap.add_argument("--jsonl", help="조각을 JSONL로도 저장 (git 제외 경로만)")
    ap.add_argument("--no-db", action="store_true", help="DB에 쓰지 않는다")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    jsonl = Path(args.jsonl).resolve() if args.jsonl else None
    if jsonl and not _git_ignored(jsonl):
        print(f"--jsonl 경로가 git 제외가 아님 (커밋될 수 있음): {jsonl}", file=sys.stderr)
        return 1

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    chunks, report = build_index(cfg, extractor or PdfplumberExtractor())
    totals = report.to_dict()["totals"]
    if not chunks:
        print(f"조각이 0개라 멈춤 (건너뜀 {totals['skipped']}개, 보고서 확인)", file=sys.stderr)
        return 1

    if jsonl:
        jsonl.parent.mkdir(parents=True, exist_ok=True)
        with jsonl.open("w", encoding="utf-8") as f:
            for c in chunks:
                f.write(c.model_dump_json() + "\n")
    if not args.no_db:
        engine = create_engine(get_settings().database_url)
        try:
            with Session(engine) as session:
                write_index(session, chunks)
        finally:
            engine.dispose()

    print(
        f"문헌 {totals['docs']}개, 조각 {totals['chunks']}개 {totals['chunks_by_kind']}, "
        f"removed_lines {totals['removed_lines']}, 건너뜀 {totals['skipped']}개"
        f"{'' if not args.no_db else ' (DB 안 씀)'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
