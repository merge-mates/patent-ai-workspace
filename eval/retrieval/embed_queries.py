"""정답 파일의 질의 → {질의: 벡터} 파일 (#66). vector 검색기의 settings.query_vectors로 넘긴다.

정답 파일(data/goldsets/)은 채점기 쪽만 읽는다. 모델 호출은 core의 embed()를 거친다.
파일에는 질의 원문이 들어 있어 git 밖(work/)에 둔다. 로그에는 개수만 남긴다.

실행:
  uv run --env-file <.env> python -m eval.retrieval.embed_queries \
      --config config/index/law-idx-v2.yaml \
      --gold <goldsets_root>/tune/retrieval/law_gold.jsonl \
      --out work/retrieval/<실험>/query_vectors.json
"""

import argparse
import logging
import sys
from pathlib import Path

from eval.retrieval.errors import RetrievalEvalError
from eval.retrieval.gold import load_gold
from patent_ai.core.index_embed import (
    RUN_ERRORS,
    IndexEmbedError,
    call_report,
    embed_queries,
    load_index_config,
    new_context,
    write_query_vectors,
)
from patent_ai.core.llm.limits import RunContext

logger = logging.getLogger(__name__)


def main(
    argv: list[str] | None = None,
    ctx: RunContext | None = None,
    config_dir: Path | None = None,
) -> int:
    """ctx·config_dir은 테스트가 가짜 전송층과 임시 설정을 넣을 때만 준다."""
    ap = argparse.ArgumentParser(prog="eval.retrieval.embed_queries")
    ap.add_argument("--config", required=True, help="config/index/<판>.yaml (embed_step을 읽음)")
    ap.add_argument("--gold", required=True, help="정답 jsonl")
    ap.add_argument("--out", required=True, help="질의 벡터 json (git 밖)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        cfg = load_index_config(args.config, ("index_version", "embed_step"))
        if Path(args.out).exists():
            raise IndexEmbedError(f"이미 있는 파일이라 덮어쓰지 않는다: {args.out}")
        # 0줄·모양이 틀린 정답 파일이면 load_gold가 이유와 함께 멈춘다
        queries = [row.query for row in load_gold(args.gold)]
        ctx = ctx or new_context(f"embed-queries-{cfg['index_version']}")
        vectors = embed_queries(queries, cfg["embed_step"], ctx, config_dir)
        write_query_vectors(vectors, args.out)
    except (RetrievalEvalError, *RUN_ERRORS) as e:
        logger.error("%s", e)
        return 1
    # 질의 원문은 로그에 남기지 않는다 (개수만)
    logger.info("만듦: %s (질의 %d개). %s", args.out, len(vectors), call_report(ctx))
    return 0


if __name__ == "__main__":
    sys.exit(main())
