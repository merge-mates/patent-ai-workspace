"""문헌 통째 LLM 검색 (impl 이름 whole_doc_llm, 이슈 #248).

그 OA 인용문헌의 조각 전부를 번호 붙여 한 번에 모델에 넣고, 관련 조각 번호를 순위로 받는다.
모델 호출은 core/llm call_model만 거친다 (캐시·호출 상한·호출 기록).
retrieval 계약(Searcher)을 따르므로 get_searcher("whole_doc_llm", ...)로 고른다.
"""

import logging
from datetime import date
from pathlib import Path

from pydantic import BaseModel

from patent_ai.core.llm.client import call_model
from patent_ai.core.llm.config import REPO_ROOT
from patent_ai.core.llm.errors import ModelOutputInvalid
from patent_ai.core.llm.limits import RunContext
from patent_ai.retrieval.contract import register_impl
from patent_ai.retrieval.schemas import (
    Chunk,
    Corpus,
    Mode,
    SearchHit,
    SearchResult,
    SearchScope,
)

logger = logging.getLogger(__name__)

STEP = "cite_rank.whole_doc"
ATTEMPTS = 2  # 출력 검사 실패 때 1회 더 (max_retries는 전송 오류용이라 따로)


class Ranked(BaseModel):
    ranked: list[int]


def _sort_key(c: Chunk) -> tuple[str, int, str]:
    # 문헌 -> 문단 위치 순서. 위치가 없으면 그 문헌의 맨 뒤 (저장소는 순서를 보장하지 않는다)
    return (c.doc_id, c.location.start if c.location.start is not None else 10**9, c.chunk_id)


def build_variables(query: str, scope_chunks: list[Chunk]) -> tuple[dict, list[Chunk]]:
    """프롬프트 변수와 번호 순서대로 정렬한 조각을 돌려준다 (순수 함수).

    번호는 1부터. 한 줄은 `[번호] (문헌n 위치) 글자`. 문헌 순번은 정렬된 문헌 순서대로 1부터.
    """
    scope = sorted(scope_chunks, key=_sort_key)
    doc_no = {d: i for i, d in enumerate(dict.fromkeys(c.doc_id for c in scope), start=1)}
    lines = [
        f"[{i}] (문헌{doc_no[c.doc_id]} {c.location.label or ''}) {c.text}"
        for i, c in enumerate(scope, start=1)
    ]
    return {"query": query, "chunks": "\n".join(lines)}, scope


@register_impl("whole_doc_llm")
class WholeDocLLMSearcher:
    def __init__(self, repo, settings: dict, embed=None) -> None:
        # 모델 호출의 캐시·상한·기록은 실행 문맥에 있다. 없으면 조용히 캐시 없이 돌지 않게 멈춘다
        ctx = settings.get("run_context")
        if not isinstance(ctx, RunContext):
            raise ValueError("settings에 run_context(RunContext)가 없다")
        self._repo = repo
        self._index_version = settings["index_version"]
        self._ctx = ctx
        self._config_dir = Path(settings["config_dir"]) if settings.get("config_dir") else None
        self._root = Path(settings["root"]) if settings.get("root") else REPO_ROOT

    def search(
        self,
        query: str,
        corpus: Corpus,
        mode: Mode,
        k: int,
        doc_ids: list[str] | None = None,
        as_of: date | None = None,
    ) -> SearchResult:
        base = {
            "corpus": corpus,
            "index_version": self._index_version,
            "mode": mode,
            "scope": SearchScope(doc_ids=doc_ids, as_of=as_of, k=k),
        }
        chunks = self._repo.chunks(corpus, self._index_version, doc_ids, as_of)
        if not chunks:
            # 본문이 없으면 못 찾음이 아니라 확인되지 않음
            return SearchResult(**base, status="unverified", status_reason="body_missing")
        variables, scope = build_variables(query, chunks)

        # 출력 검사에 떨어지면 한 번 더. 호출 상한·전송 오류 예외는 잡지 않고 올린다
        parsed: Ranked | None = None
        for attempt in range(1, ATTEMPTS + 1):
            try:
                res = call_model(
                    STEP,
                    variables,
                    Ranked,
                    attempt=attempt,
                    ctx=self._ctx,
                    config_dir=self._config_dir,
                    root=self._root,
                )
            except ModelOutputInvalid as e:
                logger.warning("%s: 출력 검사 실패 (%d/%d): %s", STEP, attempt, ATTEMPTS, e)
                continue
            assert isinstance(res.parsed, Ranked)
            parsed = res.parsed
            break
        if parsed is None:
            return SearchResult(**base, status="unverified", status_reason="not_extracted")

        # 목록 밖 번호·중복은 버린다 (몇 개 버렸는지 경고)
        seen: set[int] = set()
        order: list[Chunk] = []
        dropped = 0
        for n in parsed.ranked:
            if 1 <= n <= len(scope) and n not in seen:
                seen.add(n)
                order.append(scope[n - 1])
            else:
                dropped += 1
        if dropped:
            logger.warning(
                "%s: 목록 밖·중복 번호 %d개를 버림 (낸 번호 %d개)",
                STEP,
                dropped,
                len(parsed.ranked),
            )
        if parsed.ranked and not order:
            # 번호를 냈는데 쓸 수 있는 게 하나도 없으면 "못 찾음"이 아니라 출력 실패
            return SearchResult(**base, status="unverified", status_reason="not_extracted")
        if not order:
            return SearchResult(**base, status="not_found_in_scope")
        # 모델이 준 순서가 순위. 점수는 순위 역순 (계약: 점수 내림차순)
        hits = [
            SearchHit(**c.model_dump(), score=float(len(order) - i), rank=i + 1)
            for i, c in enumerate(order[:k])
        ]
        return SearchResult(**base, hits=hits)
