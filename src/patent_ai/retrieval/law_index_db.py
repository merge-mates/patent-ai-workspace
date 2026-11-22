"""색인 조각 JSONL → DB law_chunks / cite_chunks 표 (#66 task 4, #67 m2-i2 task-2).

말뭉치(`--corpus law|cite`, 기본 law)마다 표가 하나다. 파일 이름은 law_index_db 그대로 둔다
(옮기면 지시서 명령·문서 링크가 다 바뀐다).

지키는 선 (공유 DB, 사용자 11/19 규칙의 예외 범위만):
- 그 말뭉치 표에서 이번 index_version 줄만 지우고 다시 넣는다. 다른 표·다른 판은 안 건드린다.
- DB에 그 판이 이미 있으면 내용이 같을 때만 다시 넣는다. 다르면 멈추고 새 판을 만들게 한다.
- 지우기·넣기·세기를 한 트랜잭션으로 묶는다. 넣은 수가 JSONL 줄 수와 다르면 되돌린다.
- 판 이름이 law-idx-v<N>가 아니거나, 다른 판 조각이 섞였거나, 0개면 DB를 건드리기 전에 멈춘다.

실행 (사람이 확인한 뒤):
  uv run python -m patent_ai.retrieval.law_index_db --jsonl data/processed/law/law-idx-v1.jsonl \
      --index-version law-idx-v1
  uv run python -m patent_ai.retrieval.law_index_db --corpus cite \
      --jsonl data/processed/cite_search/cite-idx-v2.jsonl --index-version cite-idx-v2
"""

import argparse
import hashlib
import json
import logging
import struct
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import Delete, create_engine, delete, func, select
from sqlalchemy.orm import Session

from patent_ai.db.models.chunks import CiteChunk, LawChunk
from patent_ai.index_version import is_db_index_version, is_index_version
from patent_ai.retrieval.errors import RetrievalError
from patent_ai.retrieval.repository import (
    InMemoryChunkRepository,
    chunk_problem,
    chunk_to_row,
    fill_law_defaults,
    row_to_chunk,
)
from patent_ai.retrieval.schemas import Chunk, Corpus
from patent_ai.settings import get_settings

logger = logging.getLogger(__name__)

# 말뭉치마다 표와 판 이름 꼴이 하나씩 (판 이름 앞말이 말뭉치 이름)
_TABLES = {"law": LawChunk, "cite": CiteChunk}


class IndexDbError(RetrievalError):
    """색인을 DB에 넣을 수 없다."""


def _check_corpus(corpus: str) -> None:
    if corpus not in _TABLES:
        raise IndexDbError(f"말뭉치가 아니다: {corpus!r} (law|cite)")


def delete_statement(corpus: Corpus, index_version: str) -> Delete:
    """지우는 문장: 그 말뭉치 표의 그 판 줄만."""
    _check_corpus(corpus)
    table = _TABLES[corpus]
    return delete(table).where(table.index_version == index_version)


def _check(chunks: Sequence[Chunk], corpus: Corpus, index_version: str) -> None:
    _check_corpus(corpus)
    if not is_index_version(corpus, index_version):
        raise IndexDbError(f"{corpus} 색인 판 이름이 아니다: {index_version!r}")
    if not is_db_index_version(corpus, index_version):
        # us 줄 판은 DB CHECK가 아직 안 받는다. 세션을 열기 전에 멈춘다
        raise IndexDbError(
            f"us 줄 판은 DB CHECK가 아직 안 받는다 (jsonl·--chunks로만): {index_version!r}"
        )
    if not chunks:
        raise IndexDbError("넣을 조각이 0개다")
    other = sum(c.index_version != index_version for c in chunks)
    if other:
        raise IndexDbError(f"{index_version}이 아닌 조각 {other}개가 섞였다")
    # 법령 표: 판본 not_applicable은 판례·심결만, 선고일·발언 주체는 판례·심결만 (db 검사 함수)
    for c in chunks:
        reason = chunk_problem(corpus, c)
        if reason:
            raise IndexDbError(f"{c.chunk_id}: {reason}")
    # 인용문헌 표에는 판본 not_applicable만 넣는다
    if corpus == "cite":
        na = sum(c.edition.status == "not_applicable" for c in chunks)
        if na != len(chunks):
            raise IndexDbError(
                f"인용문헌 표에는 판본 not_applicable만 넣는다 ({len(chunks) - na}개 아님)"
            )


def _as_float32(chunk: Chunk) -> Chunk:
    """벡터를 float32로 맞춘다. pgvector는 float32로 저장해 읽을 때 값이 바뀌기 때문이다."""
    if chunk.embedding is None:
        return chunk
    f32 = [struct.unpack("<f", struct.pack("<f", x))[0] for x in chunk.embedding]
    return chunk.model_copy(update={"embedding": f32})


def content_sha256(chunks: Sequence[Chunk]) -> str:
    """조각 내용 전체(글·위치·판본·벡터 포함)의 해시. 순서와 상관없다.

    JSONL(float64)과 DB에서 다시 읽은 값(float32)이 같은 해시가 되도록 벡터를 먼저 float32로 맞춘다.
    """
    # attrs 같은 dict는 키 순서를 정렬해 해시한다 (JSONB가 키를 다시 정렬해 돌려준다)
    lines = sorted(
        json.dumps(_as_float32(c).model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        for c in chunks
    )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def replace_index(
    session: Session, chunks: Sequence[Chunk], corpus: Corpus, index_version: str
) -> int:
    """그 판 줄을 지우고 chunks를 넣는다. 넣은 뒤 DB에서 센 수를 돌려준다."""
    # 1) DB를 건드리기 전에 다 검사한다
    _check(chunks, corpus, index_version)
    if corpus == "law":
        chunks = [fill_law_defaults(c) for c in chunks]  # DB에서 읽은 행과 같은 모양으로
    # 2) 한 트랜잭션: 중간에 실패하거나 수가 다르면 예전 줄이 그대로 남는다
    with session.begin():
        # 같은 판 이름에 다른 내용을 덮어쓰지 않는다 (덤프를 받은 쪽과 지문이 어긋남)
        table = _TABLES[corpus]
        rows = session.scalars(select(table).where(table.index_version == index_version))
        existing = [row_to_chunk(r) for r in rows]
        if existing and content_sha256(existing) != content_sha256(chunks):
            raise IndexDbError(
                f"DB의 {index_version} 내용({len(existing)}개)이 새 조각과 다르다. "
                "설정·청커를 바꿨으면 새 판(v<N+1>)으로 만든다"
            )
        session.execute(delete_statement(corpus, index_version))
        session.add_all(chunk_to_row(corpus, c) for c in chunks)
        n = session.scalar(
            select(func.count()).select_from(table).where(table.index_version == index_version)
        )
        if n != len(chunks):
            raise IndexDbError(f"넣은 수 {n}이 조각 수 {len(chunks)}와 다르다 (되돌림)")
    return n


def read_chunks_jsonl(path: str | Path, corpus: Corpus) -> list[Chunk]:
    """JSONL 줄을 판으로 거르지 않고 다 읽는다. 섞인 판은 replace_index 검사가 잡는다."""
    # 저장소 검사(chunk_id 겹침·말뭉치 판 앞말·판본 상태)를 먼저 거친다
    InMemoryChunkRepository.from_jsonl(corpus, path)
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    chunks = [Chunk.model_validate_json(line) for line in lines if line.strip()]
    # 옛 JSONL은 source_kind가 없다: statute로 채워 DB 행과 내용 지문을 맞춘다
    return [fill_law_defaults(c) for c in chunks] if corpus == "law" else chunks


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="색인 JSONL을 말뭉치 표에 다시 넣는다")
    ap.add_argument("--corpus", choices=sorted(_TABLES), default="law")
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--index-version", required=True)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        # 깨진 JSONL·없는 파일도 traceback 대신 이유 한 줄 + 종료 1
        chunks = read_chunks_jsonl(args.jsonl, args.corpus)
        with Session(create_engine(get_settings().database_url)) as session:
            n = replace_index(session, chunks, args.corpus, args.index_version)
    except (IndexDbError, ValueError, OSError) as e:
        logger.error("%s", e)
        return 1
    logger.info("넣음: %s_chunks %s 줄 %d개", args.corpus, args.index_version, n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
