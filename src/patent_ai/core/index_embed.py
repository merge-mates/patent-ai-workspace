"""색인에 벡터 채우기 (#66 B1). 모델 호출은 core/llm의 embed()로만.

- chunks: 이미 있는 판(예 law-idx-v1)의 조각 JSONL → 새 판(law-idx-v2) JSONL.
  글·위치·판본은 그대로 두고 index_version·chunk_id 앞말만 새 판, embedding을 채운다.
  같은 글은 한 번만 임베딩한다 (법령은 판마다 같은 조문이 많아 1만 조각에 글은 1천여 개).
- queries: 법령 정답 파일의 질의 → {질의: 벡터} 파일 (vector 검색기의 settings.query_vectors).
  질의 글이 들어 있어 git 밖(work/)에 둔다.

실행:
  uv run python -m patent_ai.core.index_embed chunks --config config/index/law-idx-v2.yaml
  uv run python -m patent_ai.core.index_embed queries --config config/index/law-idx-v2.yaml \
      --gold <goldsets_root>/tune/retrieval/law_gold.jsonl \
      --out work/retrieval/<실험>/query_vectors.json
"""

import argparse
import json
import logging
import re
import sys
from pathlib import Path

import yaml

from patent_ai.core.llm.embed import embed
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.retrieval.law_index import write_jsonl
from patent_ai.retrieval.law_index_db import read_chunks_jsonl
from patent_ai.retrieval.schemas import Chunk

logger = logging.getLogger(__name__)

_VERSION = re.compile(r"^(law|cite)-idx-v[0-9]+$")


class IndexEmbedError(ValueError):
    """색인에 벡터를 채울 수 없다."""


def _unique(texts: list[str]) -> list[str]:
    # 처음 나온 순서를 지켜 중복을 뺀다 (같은 입력이면 같은 호출 순서)
    return list(dict.fromkeys(texts))


def embed_chunks(
    chunks: list[Chunk],
    to_version: str,
    step: str,
    ctx: RunContext,
    config_dir: Path | None = None,
) -> list[Chunk]:
    """조각들을 새 판으로 옮기며 embedding을 채운다. 검사에서 걸리면 모델을 부르지 않는다."""
    if not chunks:
        raise IndexEmbedError("벡터를 채울 조각이 0개다")
    if not _VERSION.match(to_version):
        raise IndexEmbedError(f"색인 판 이름이 아니다: {to_version!r}")
    versions = {c.index_version for c in chunks}
    if len(versions) != 1:
        raise IndexEmbedError(f"판이 섞인 조각이다: {sorted(versions)}")
    (from_version,) = versions
    if from_version == to_version:
        raise IndexEmbedError(f"같은 판({to_version})에 덮어쓰지 않는다. 새 판 이름을 준다")
    if from_version.split("-")[0] != to_version.split("-")[0]:
        raise IndexEmbedError(f"말뭉치가 다르다: {from_version} → {to_version}")

    texts = _unique([c.text for c in chunks])
    vectors = dict(zip(texts, embed(step, texts, ctx=ctx, config_dir=config_dir), strict=True))
    prefix = from_version + ":"
    out = []
    for c in chunks:
        out.append(
            c.model_copy(
                update={
                    "index_version": to_version,
                    "chunk_id": to_version + ":" + c.chunk_id.removeprefix(prefix),
                    "embedding": vectors[c.text],
                }
            )
        )
    logger.info("조각 %d개, 임베딩한 글 %d개", len(out), len(texts))
    return out


def embed_queries(
    queries: list[str], step: str, ctx: RunContext, config_dir: Path | None = None
) -> dict[str, list[float]]:
    """질의 → 벡터. 같은 질의는 한 번만."""
    uniq = _unique(queries)
    return dict(zip(uniq, embed(step, uniq, ctx=ctx, config_dir=config_dir), strict=True))


def write_query_vectors(vectors: dict[str, list[float]], out: str | Path) -> None:
    """{질의: 벡터} JSON. 있는 파일은 덮어쓰지 않는다."""
    p = Path(out)
    if p.exists():
        raise IndexEmbedError(f"이미 있는 파일이라 덮어쓰지 않는다: {p}")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(vectors, ensure_ascii=False), encoding="utf-8")


def _report(ctx: RunContext) -> str:
    recs = ctx.recorder.records  # type: ignore[attr-defined]
    calls = sum(r.outcome == "ok" for r in recs)
    tokens = sum(r.input_tokens for r in recs)
    cost = sum(r.cost or 0.0 for r in recs)
    return f"호출 {calls}번, 입력 토큰 {tokens}, 비용 ${cost:.4f}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="색인 조각·질의에 벡터 채우기")
    ap.add_argument("what", choices=["chunks", "queries"])
    ap.add_argument("--config", required=True, help="config/index/<판>.yaml")
    ap.add_argument("--gold", help="queries: 정답 jsonl")
    ap.add_argument("--out", help="queries: 질의 벡터 json")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    # 실행마다 새 상한·기록. 전송층·캐시를 안 주면 진짜 전송층 + 기본 파일 캐시 (설정의 상한 필수)
    ctx = RunContext(f"index-embed-{cfg['index_version']}", CallBudget(), MemoryRecorder())
    try:
        if args.what == "chunks":
            chunks = read_chunks_jsonl(cfg["from"])
            out = embed_chunks(chunks, cfg["index_version"], cfg["embed_step"], ctx)
            write_jsonl(out, cfg["out"])
            logger.info("만듦: %s (조각 %d개). %s", cfg["out"], len(out), _report(ctx))
        else:
            if not args.gold or not args.out:
                ap.error("queries에는 --gold와 --out이 필요하다")
            lines = Path(args.gold).read_text(encoding="utf-8").splitlines()
            queries = [json.loads(line)["query"] for line in lines if line.strip()]
            if not queries:
                raise IndexEmbedError("정답 파일에 질의가 0개다")
            write_query_vectors(embed_queries(queries, cfg["embed_step"], ctx), args.out)
            # 질의 글은 로그에 안 남긴다 (개수만)
            logger.info("만듦: %s (질의 %d개). %s", args.out, len(set(queries)), _report(ctx))
    except (IndexEmbedError, ValueError) as e:
        logger.error("%s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
