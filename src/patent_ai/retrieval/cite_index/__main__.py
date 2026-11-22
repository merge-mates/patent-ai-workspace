"""색인 명령: PDF 폴더 → 쪽 글자 → 머리말·꼬리말 빼기 → 조각 → cite_chunks + 보고 (design 2절).

문서 글자는 어디에도 찍지 않는다. 보고에는 숫자와 파일 이름·이유만 둔다.
"""

import argparse
import hashlib
import json
import logging
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from patent_ai.db.models.chunks import CiteChunk
from patent_ai.git_paths import is_git_ignored
from patent_ai.retrieval.cite_index.chunker import (
    ChunkingConfig,
    UsChunkingConfig,
    chunk_document_checked,
    is_granted_doc,
)
from patent_ai.retrieval.cite_index.columns import (
    GrantedConfig,
    GrantedPage,
    PdfplumberColumnExtractor,
    PdfplumberGrantedExtractor,
)
from patent_ai.retrieval.cite_index.header_footer import HeaderFooterConfig, strip_repeated
from patent_ai.retrieval.cite_index.pages import PageExtractor, PageText, PdfplumberExtractor
from patent_ai.retrieval.repository import chunk_to_row
from patent_ai.retrieval.schemas import Chunk
from patent_ai.settings import get_settings

log = logging.getLogger("patent_ai.cite_index")

REPO_ROOT = Path(__file__).resolve().parents[4]
# 한국 공보 파일 이름은 그대로 doc_id (KR10…A, KR10…B1 등)
_KR_STEM = re.compile(r"^KR\d+[AB]\d?$")
# 미국 공보도 파일 이름이 그대로 doc_id (US2013…A1, US7…B2 등)
_US_STEM = re.compile(r"^US\d+[AB]\d?$")


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
    return ChunkingConfig.from_dict(cfg["chunking"])


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


def build_index(
    cfg: dict,
    extractor: PageExtractor,
    column_extractor: PageExtractor | None = None,
    granted_extractor=None,
) -> tuple[list[Chunk], IndexReport]:
    iv = cfg["index_version"]
    hf = HeaderFooterConfig.from_dict(cfg["header_footer"])
    chunking = _chunking_config(cfg)
    us_chunking = UsChunkingConfig.from_dict(cfg["us_chunking"]) if "us_chunking" in cfg else None
    # 미국 공보는 두 단이라 단 순서 추출기를 쓴다 (안 주면 같은 추출기)
    column_extractor = column_extractor or extractor
    granted_extractor = granted_extractor or column_extractor  # 등록공보 (칼럼·줄 배치까지)
    granted_cfg = GrantedConfig.from_dict(cfg.get("us_granted") or {})
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
        elif _KR_STEM.match(stem) or _US_STEM.match(stem):
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
            if is_granted_doc(doc_id):
                use = granted_extractor
            else:
                use = column_extractor if doc_id.startswith("US") else extractor
            pages = use.extract(pdf)
        except Exception as e:  # noqa: BLE001 한 문헌의 오류가 전체를 멈추지 않게
            reason = f"추출 오류: {type(e).__name__}: {e}"
            log.warning("건너뜀 %s: %s", stem, reason)
            skip(stem, reason)
            continue

        if is_granted_doc(doc_id):
            # 칼럼·줄 조각은 머리줄을 이미 뺐다. 쪽 조각·요약에 쓰는 줄만 되풀이 줄을 뺀다
            sp, removed = strip_repeated(
                [PageText(page=p.page, lines=p.lines) for p in pages],
                hf.scan_lines,
                hf.min_page_ratio,
                hf.keep_patterns,
            )
            stripped = [
                GrantedPage(p.page, q.lines, p.columns) for p, q in zip(pages, sp, strict=True)
            ]
        else:
            stripped, removed = strip_repeated(
                pages, hf.scan_lines, hf.min_page_ratio, hf.keep_patterns
            )
        doc_chunks, warns, check = chunk_document_checked(
            doc_id, stripped, iv, chunking, us_chunking, granted_cfg
        )
        for w in warns:
            log.warning(w)
        chunks.extend(doc_chunks)
        report.docs[doc_id] = {
            "pages": len(pages),
            "chunks": dict(Counter(c.chunk_kind for c in doc_chunks)),
            "removed_lines": removed,
            # 이유를 보고에서 가를 수 있게 문구 그대로 (doc_id·키만 들어 있음)
            "warnings": list(warns),
        }
        if check is not None:  # 공개공보는 문단 번호, 등록공보는 칼럼·줄 검사 숫자
            key = "column_check" if is_granted_doc(doc_id) else "paragraph_check"
            report.docs[doc_id][key] = check

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


def main(argv: list[str] | None = None, extractor: PageExtractor | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cite_index")
    ap.add_argument("--config", required=True)
    ap.add_argument("--jsonl", help="조각을 JSONL로도 저장 (git 제외 경로만)")
    ap.add_argument("--no-db", action="store_true", help="DB에 쓰지 않는다")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    jsonl = Path(args.jsonl).resolve() if args.jsonl else None
    # 저장소 밖이거나 git이 무시하지 않는 경로는 커밋될 수 있어 거절한다
    if jsonl and not is_git_ignored(jsonl):
        print(f"--jsonl 경로가 git 제외가 아님 (커밋될 수 있음): {jsonl}", file=sys.stderr)
        return 1

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    chunks, report = build_index(
        cfg,
        extractor or PdfplumberExtractor(),
        extractor
        or PdfplumberColumnExtractor(**cfg.get("us_columns", {})),  # 주어지면 모두 그것으로
        extractor
        or PdfplumberGrantedExtractor(
            GrantedConfig.from_dict(cfg.get("us_granted") or {}), **cfg.get("us_columns", {})
        ),
    )
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
