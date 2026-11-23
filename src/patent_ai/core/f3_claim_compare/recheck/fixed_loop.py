"""근거 다시 찾기 고정 루프(B): 코드가 정한 순서로 한 번 더 찾는다.

못 찾은 구성요소 × 인용문헌 하나마다
  1) 모델이 구성요소를 다른 말 질의 n개로 다시 쓴다 (call_model "recheck.rewrite")
  2) 질의마다 그 인용문헌 안에서 hybrid 검색 (상위 rewrite_k)
  3) 1차에 보여 준 조각은 빼고 합친다 -> 판정할 후보
검색 기록은 질의마다 round=2 한 줄. 다시 쓰기가 실패하면 예외를 그대로 올린다
(보류로 바꾸는 것은 부르는 쪽 몫: 이 함수는 실패를 성공으로 숨기지 않는다).
"""

import logging
from collections.abc import Collection

from pydantic import BaseModel, ConfigDict, Field

from patent_ai.core.agents.tool_loop import LoopStep, RecheckToolFailed, call_environment
from patent_ai.core.bundle_errors import BUNDLE_ERRORS
from patent_ai.core.f3_claim_compare.citations import ResolvedCitation
from patent_ai.core.f3_claim_compare.elements import ClaimElement
from patent_ai.core.f3_claim_compare.inputs import F3Settings
from patent_ai.core.f3_claim_compare.recheck.config import RecheckSettings
from patent_ai.core.f3_claim_compare.result import SearchLogRow
from patent_ai.core.f3_claim_compare.textmatch import text_hash
from patent_ai.core.llm.client import call_model
from patent_ai.core.llm.errors import ModelOutputInvalid
from patent_ai.core.llm.limits import RunContext
from patent_ai.retrieval.contract import Searcher

logger = logging.getLogger(__name__)

STEP = "recheck.rewrite"


class RewriteAnswer(BaseModel):
    """모델 답: 다시 쓴 질의들. 개수 상한(n)은 설정 값이라 코드가 자른다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    queries: list[str] = Field(min_length=1)


def rewrite_queries(element_text: str, claim_text: str, ctx: RunContext, *, n: int) -> list[str]:
    """구성요소를 다른 말 질의 최대 n개로 다시 쓴다. 빈 질의·같은 질의는 빼고 앞에서 n개만 쓴다.

    호출 실패(ModelCallFailed·ModelOutputInvalid·ModelCallLimitExceeded)는 그대로 올라간다.
    """
    variables = {"n": str(n), "claim_text": claim_text, "element": element_text}
    answer = call_model(STEP, variables, RewriteAnswer, ctx=ctx).parsed
    queries = list(dict.fromkeys(q.strip() for q in answer.queries if q.strip()))
    if not queries:
        # 빈 질의뿐이면 찾지도 않고 "못 찾음"이 되므로 모델 답 오류로 올린다 (호출자가 보류로)
        raise ModelOutputInvalid("recheck.rewrite: 쓸 수 있는 질의가 0개")
    if len(queries) > n:
        logger.warning("recheck.rewrite: 질의 %d개를 받아 앞 %d개만 씀", len(queries), n)
    return queries[:n]


def _scope(cite: ResolvedCitation, settings: F3Settings, recheck: RecheckSettings, n: int) -> str:
    """다시 찾아본 범위를 사람이 읽는 글로."""
    s = settings.search
    return (
        f"{cite.label} 조각 {cite.chunk_count}개 중 {s.impl} 상위 {recheck.search.rewrite_k} "
        f"({s.index_version}) · 다시 찾기(fixed_loop): 질의 {n}개"
    )


def fixed_loop_candidates(
    *,
    unit_id: str,
    claim: int,
    item_n: int,
    element: ClaimElement,
    claim_text: str,
    cite: ResolvedCitation,
    shown: Collection[str],
    settings: F3Settings,
    recheck: RecheckSettings,
    ctx: RunContext,
    searcher: Searcher,
    search_log: list[SearchLogRow],
    queries_out: list[str] | None = None,
    steps_out: list[LoopStep] | None = None,
) -> dict:
    """구성요소 하나 × 인용문헌 하나의 다시 찾기 후보 {chunk_id: _Candidate}.

    shown = 1차에 모델에 보여 준 조각 ID (후보에서 뺀다). item_n = 모델에 보여 주는 구성요소 번호.
    질의마다 검색 기록(round=2)을 search_log에 더한다. queries_out을 주면 다시 쓴 질의를 거기 담는다
    (부르는 쪽이 근거 줄·다시 찾기 기록에 질의를 적는다. 중간에 실패해도 쓴 질의까지는 남는다).
    steps_out에는 실제 호출한 검색을 성공·실패와 함께 남긴다.
    """
    # compare.py가 이 모듈을 부르게 되면 맞물려 import되므로 함수 안에서 가져온다
    from patent_ai.core.f3_claim_compare.compare import (
        _Candidate,
        _mode,
        _second_log_status,
    )

    if cite.doc_id is None:  # 본문 없는 인용문헌은 부르는 쪽이 이미 보류한다
        raise ValueError(f"{cite.label}: doc_id가 없어 다시 찾을 수 없다")
    queries = rewrite_queries(element.text, claim_text, ctx, n=recheck.search.rewrite_n)
    if queries_out is not None:
        queries_out.extend(queries)
    mode = _mode(settings.search.impl)
    tool_name = f"search_{mode}"
    k = recheck.search.rewrite_k
    scope = _scope(cite, settings, recheck, len(queries))
    candidates: dict[str, _Candidate] = {}
    for query in queries:
        # 검색기·DB 예외는 그 구성요소만 tool_failed 보류가 되게 감싼다 (에이전트와 같은 함수)
        logged = {"query": query, "k": k}
        try:
            result = call_environment(
                f"{mode} 검색",
                lambda q=query: searcher.search(q, "cite", mode, k, doc_ids=[cite.doc_id]),
            )
        except (*BUNDLE_ERRORS, RecheckToolFailed):
            if steps_out is not None:
                steps_out.append(LoopStep(1, tool_name, logged, [], True))
            raise
        if steps_out is not None:
            steps_out.append(
                LoopStep(1, tool_name, logged, [h.chunk_id for h in result.hits], False)
            )
        fresh = [h for h in result.hits if h.chunk_id not in shown]
        search_log.append(
            SearchLogRow(
                unit_id=unit_id,
                claim=claim,
                element_claim=element.claim,
                element_no=element.no,
                element_hash=text_hash(element.text),
                citation=cite.label,
                doc_id=cite.doc_id,
                round=2,
                status=_second_log_status(result, bool(fresh), scope),
                searched_scope=scope,
                hit_chunk_ids=[h.chunk_id for h in fresh],
            )
        )
        for hit in fresh:
            found = candidates.setdefault(hit.chunk_id, _Candidate(hit, cite.label))
            # 질의 여러 개에 걸리면 가장 높은 순위를 남긴다
            found.ranks[item_n] = min(hit.rank, found.ranks.get(item_n, hit.rank))
    if not candidates:
        logger.warning(
            "recheck 청구항 %d 구성요소 %d %s: 다시 찾기에서 새 조각이 0개",
            claim,
            element.no,
            cite.label,
        )
    return candidates
