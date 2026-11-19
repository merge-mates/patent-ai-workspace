"""법령 색인 조각 JSONL → DB law_chunks 표 (#66 task 4).

지키는 선 (공유 DB, 사용자 11/19 규칙의 예외 범위만):
- law_chunks 표에서 이번 index_version 줄만 지우고 다시 넣는다. 다른 표·다른 판은 안 건드린다.
- 지우기·넣기·세기를 한 트랜잭션으로 묶는다. 넣은 수가 JSONL 줄 수와 다르면 되돌린다.
- 판 이름이 law-idx-v<N>가 아니거나, 다른 판 조각이 섞였거나, 0개면 DB를 건드리기 전에 멈춘다.

실행 (사람이 확인한 뒤):
  uv run python -m patent_ai.retrieval.law_index_db --jsonl data/processed/law/law-idx-v1.jsonl \
      --index-version law-idx-v1
"""

import argparse
import logging
import re
import sys
from collections.abc import Sequence

from sqlalchemy import Delete, create_engine, delete, func, select
from sqlalchemy.orm import Session

from patent_ai.db.models.chunks import LawChunk
from patent_ai.retrieval.errors import RetrievalError
from patent_ai.retrieval.repository import InMemoryChunkRepository, chunk_to_row
from patent_ai.retrieval.schemas import Chunk
from patent_ai.settings import get_settings

logger = logging.getLogger(__name__)

_LAW_VERSION = re.compile(r"^law-idx-v[0-9]+$")


class LawIndexDbError(RetrievalError):
    """법령 색인을 DB에 넣을 수 없다."""


def delete_statement(index_version: str) -> Delete:
    """지우는 문장: law_chunks 표의 그 판 줄만."""
    return delete(LawChunk).where(LawChunk.index_version == index_version)


def _check(chunks: Sequence[Chunk], index_version: str) -> None:
    if not _LAW_VERSION.match(index_version):
        raise LawIndexDbError(f"법령 색인 판 이름이 아니다: {index_version!r}")
    if not chunks:
        raise LawIndexDbError("넣을 조각이 0개다")
    other = sum(c.index_version != index_version for c in chunks)
    if other:
        raise LawIndexDbError(f"{index_version}이 아닌 조각 {other}개가 섞였다")
    na = sum(c.edition.status == "not_applicable" for c in chunks)
    if na:
        raise LawIndexDbError(f"판본 not_applicable 조각 {na}개는 법령 표에 못 넣는다")


def replace_law_index(session: Session, chunks: Sequence[Chunk], index_version: str) -> int:
    """그 판 줄을 지우고 chunks를 넣는다. 넣은 뒤 DB에서 센 수를 돌려준다."""
    # 1) DB를 건드리기 전에 다 검사한다
    _check(chunks, index_version)
    # 2) 한 트랜잭션: 중간에 실패하거나 수가 다르면 예전 줄이 그대로 남는다
    with session.begin():
        session.execute(delete_statement(index_version))
        session.add_all(chunk_to_row("law", c) for c in chunks)
        n = session.scalar(
            select(func.count())
            .select_from(LawChunk)
            .where(LawChunk.index_version == index_version)
        )
        if n != len(chunks):
            raise LawIndexDbError(f"넣은 수 {n}이 조각 수 {len(chunks)}와 다르다 (되돌림)")
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="법령 색인 JSONL을 law_chunks 표에 다시 넣는다")
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--index-version", required=True)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # 저장소의 JSONL 검사(chunk_id 겹침·판본 상태)를 그대로 거친다
    chunks = InMemoryChunkRepository.from_jsonl("law", args.jsonl).chunks(
        "law", args.index_version, None, None
    )
    try:
        with Session(create_engine(get_settings().database_url)) as session:
            n = replace_law_index(session, chunks, args.index_version)
    except LawIndexDbError as e:
        logger.error("%s", e)
        return 1
    logger.info("넣음: law_chunks %s 줄 %d개", args.index_version, n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
