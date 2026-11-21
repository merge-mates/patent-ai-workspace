"""색인에 벡터 채우기 (#66 B1). 모델 호출은 core/llm의 embed()로만.

- chunks: 이미 있는 판(예 law-idx-v1)의 조각 JSONL → 새 판(law-idx-v2) JSONL.
  글·위치·판본은 그대로 두고 index_version·chunk_id 앞말만 새 판, embedding을 채운다.
  같은 글은 한 번만 임베딩한다 (법령은 판마다 같은 조문이 많아 1만 조각에 글은 1천여 개).
- 질의 벡터는 정답 파일을 읽어야 해서 채점기 쪽 `eval/retrieval/embed_queries.py`가 만든다
  (앱 코드는 data/goldsets/를 읽지 않는다). 여기에는 글 목록 → 벡터 함수만 둔다.

실행:
  uv run python -m patent_ai.core.index_embed chunks --config config/index/law-idx-v2.yaml
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import yaml

from patent_ai.core.llm.embed import embed
from patent_ai.core.llm.errors import ModelCallFailed, ModelCallLimitExceeded, ModelConfigError
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.index_version import corpus_of
from patent_ai.retrieval.law_index import write_jsonl
from patent_ai.retrieval.law_index_db import read_chunks_jsonl
from patent_ai.retrieval.schemas import Chunk

logger = logging.getLogger(__name__)


# 실패하면 한 줄로 알리고 1로 끝낼 오류들 (성공 종료하지 않음)
RUN_ERRORS = (ValueError, OSError, ModelConfigError, ModelCallFailed, ModelCallLimitExceeded)


class IndexEmbedError(ValueError):
    """색인에 벡터를 채울 수 없다."""


def unique(texts: list[str]) -> list[str]:
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
    if corpus_of(to_version) is None:
        raise IndexEmbedError(f"색인 판 이름이 아니다: {to_version!r}")
    versions = {c.index_version for c in chunks}
    if len(versions) != 1:
        raise IndexEmbedError(f"판이 섞인 조각이다: {sorted(versions)}")
    (from_version,) = versions
    if from_version == to_version:
        raise IndexEmbedError(f"같은 판({to_version})에 덮어쓰지 않는다. 새 판 이름을 준다")
    if corpus_of(from_version) != corpus_of(to_version):
        raise IndexEmbedError(f"말뭉치가 다르다: {from_version} → {to_version}")
    prefix = from_version + ":"
    bad = [c.chunk_id for c in chunks if not c.chunk_id.startswith(prefix)]
    if bad:
        # 앞말이 없으면 새 chunk_id가 '<새 판>:<옛 id>'처럼 엉뚱해진다
        raise IndexEmbedError(f"chunk_id가 {prefix}로 시작하지 않는 조각 {len(bad)}개: {bad[0]}")

    texts = unique([c.text for c in chunks])
    vectors = dict(zip(texts, embed(step, texts, ctx=ctx, config_dir=config_dir), strict=True))
    out = [
        c.model_copy(
            update={
                "index_version": to_version,
                "chunk_id": to_version + ":" + c.chunk_id.removeprefix(prefix),
                "embedding": vectors[c.text],
            }
        )
        for c in chunks
    ]
    logger.info("조각 %d개, 임베딩한 글 %d개", len(out), len(texts))
    return out


def embed_queries(
    queries: list[str], step: str, ctx: RunContext, config_dir: Path | None = None
) -> dict[str, list[float]]:
    """질의 → 벡터. 같은 질의는 한 번만."""
    uniq = unique(queries)
    return dict(zip(uniq, embed(step, uniq, ctx=ctx, config_dir=config_dir), strict=True))


def write_query_vectors(vectors: dict[str, list[float]], out: str | Path) -> None:
    """{질의: 벡터} JSON. 있는 파일은 덮어쓰지 않는다."""
    p = Path(out)
    if p.exists():
        raise IndexEmbedError(f"이미 있는 파일이라 덮어쓰지 않는다: {p}")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(vectors, ensure_ascii=False), encoding="utf-8")


def load_index_config(path: str | Path, keys: tuple[str, ...]) -> dict:
    """색인 설정 yaml을 읽는다. 키가 빠지면 KeyError 대신 한 줄 오류 (RUN_ERRORS에 잡힘)."""
    p = Path(path)
    cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise IndexEmbedError(f"설정 파일이 비었거나 모양이 틀리다: {p.name}")
    missing = [k for k in keys if cfg.get(k) in (None, "")]
    if missing:
        raise IndexEmbedError(f"설정 {p.name}에 키가 빠짐: {', '.join(missing)}")
    return cfg


def call_report(ctx: RunContext) -> str:
    """기록기(MemoryRecorder)에 쌓인 호출 수·입력 토큰·비용 한 줄."""
    recs = ctx.recorder.records  # type: ignore[attr-defined]
    calls = sum(r.outcome == "ok" for r in recs)
    tokens = sum(r.input_tokens for r in recs)
    cost = sum(r.cost or 0.0 for r in recs)
    return f"호출 {calls}번, 입력 토큰 {tokens}, 비용 ${cost:.4f}"


def new_context(name: str) -> RunContext:
    # 실행마다 새 상한·기록. 전송층·캐시를 안 주면 진짜 전송층 + 기본 파일 캐시 (설정의 상한 필수)
    return RunContext(name, CallBudget(), MemoryRecorder())


def main(
    argv: list[str] | None = None,
    ctx: RunContext | None = None,
    config_dir: Path | None = None,
) -> int:
    """ctx·config_dir은 테스트가 가짜 전송층과 임시 설정을 넣을 때만 준다."""
    ap = argparse.ArgumentParser(description="색인 조각에 벡터 채우기")
    ap.add_argument("what", choices=["chunks"])
    ap.add_argument("--config", required=True, help="config/index/<판>.yaml")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        cfg = load_index_config(args.config, ("index_version", "from", "embed_step", "out"))
        out_path = Path(cfg["out"])
        # 돈을 쓰기 전에 덮어쓰기를 먼저 막는다
        if out_path.exists():
            raise IndexEmbedError(
                f"이미 있는 파일이라 덮어쓰지 않는다 (새 설정이면 새 판): {out_path}"
            )
        ctx = ctx or new_context(f"index-embed-{cfg['index_version']}")
        # 말뭉치는 새 판 이름 앞말에서 꺼낸다 (cite-idx-v2 → cite). 새 설정 키는 두지 않는다
        corpus = corpus_of(str(cfg["index_version"]))
        if corpus is None:
            raise IndexEmbedError(f"색인 판 이름이 아니다: {cfg['index_version']!r}")
        chunks = read_chunks_jsonl(cfg["from"], corpus)
        out = embed_chunks(chunks, cfg["index_version"], cfg["embed_step"], ctx, config_dir)
        write_jsonl(out, out_path)
    except RUN_ERRORS as e:
        logger.error("%s", e)
        return 1
    logger.info("만듦: %s (조각 %d개). %s", out_path, len(out), call_report(ctx))
    return 0


if __name__ == "__main__":
    sys.exit(main())
