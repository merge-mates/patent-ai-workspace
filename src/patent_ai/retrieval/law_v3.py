"""law-idx-v3 만들기: 조문(원본에서 다시) + 심사기준 + 판례·심결 조각을 한 판으로 모은다 (#24 24d).

- 조문은 v1과 같은 청커(`law_index.build_index`)로 판 이름만 law-idx-v3로 다시 만든다.
- 심사기준·판례·심결은 이미 만든 조각 JSONL(24b·24c)을 읽는다.
- 임베딩은 채우지 않는다 (F2 검색은 BM25). 이 판에서 vector 검색을 부르면 구현이 멈춘다.
- 자료 유형 하나라도 0개면 판을 만들지 않는다 (빈 채로 "다 있음"으로 보이지 않게).

실행: uv run python -m patent_ai.retrieval.law_v3 --config config/index/law-idx-v3.yaml
"""

import argparse
import logging
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import get_args

import yaml

from patent_ai.retrieval.errors import RetrievalError
from patent_ai.retrieval.law_index import LawIndexError, build_index, write_jsonl
from patent_ai.retrieval.law_index_db import read_chunks_jsonl
from patent_ai.retrieval.schemas import Chunk, SourceKind

logger = logging.getLogger(__name__)

_KEYS = ("index_version", "raw_dir", "laws", "parts", "out")


def merge_parts(parts: Sequence[Sequence[Chunk]], index_version: str) -> list[Chunk]:
    """조각 묶음들을 한 판으로. 다른 판·겹친 ID·빈 자료 유형이 있으면 멈춘다."""
    chunks = [c for part in parts for c in part]
    other = sorted({c.index_version for c in chunks} - {index_version})
    if other:
        raise LawIndexError(f"{index_version}이 아닌 조각이 섞였다: {other}")
    repeated = [cid for cid, n in Counter(c.chunk_id for c in chunks).items() if n > 1]
    if repeated:
        raise LawIndexError(f"chunk_id가 겹친다 ({len(repeated)}개): {repeated[0]}")
    counts = count_kinds(chunks)
    empty = [k for k in get_args(SourceKind) if not counts[k]]
    if empty:
        raise LawIndexError(f"자료 유형 조각이 0개라 판을 만들지 않는다: {empty}")
    return chunks


def count_kinds(chunks: Sequence[Chunk]) -> Counter:
    return Counter(c.source_kind for c in chunks)


def build(cfg: Mapping) -> list[Chunk]:
    missing = [k for k in _KEYS if not cfg.get(k)]
    if missing:
        raise LawIndexError(f"설정에 키가 빠짐: {missing}")
    version = cfg["index_version"]
    gaps: dict[str, list[date]] = cfg.get("missing_editions") or {}
    statutes, _ = build_index(cfg["raw_dir"], cfg["laws"], version, gaps)
    return merge_parts([statutes, *(read_chunks_jsonl(p, "law") for p in cfg["parts"])], version)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="조문·심사기준·판례·심결을 한 색인 판으로 모은다")
    ap.add_argument("--config", required=True, help="config/index/law-idx-v3.yaml")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {}
        chunks = build(cfg)
        write_jsonl(chunks, cfg["out"])
    except (RetrievalError, ValueError, OSError) as e:
        logger.error("%s", e)
        return 1
    kinds = ", ".join(f"{k} {n}" for k, n in sorted(count_kinds(chunks).items()))
    logger.info("만듦: %s (조각 %d개: %s)", cfg["out"], len(chunks), kinds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
