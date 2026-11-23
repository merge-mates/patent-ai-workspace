"""근거 다시 찾기 (가) 자리: 1차에서 근거를 못 고른 (구성요소 × 인용문헌)만 다시 찾는다.

지금 `second_search`(compare.py `_second_round`)가 있는 자리에
`recheck: fixed_loop | agent`가 들어온다 (none이면 compare.py가 이 모듈을 부르지 않고
second_search 그대로 돈다. none이 아니면 second_search는 돌지 않는다, D11).
입출력은 `_second_round`와 같다: {(구성요소 번호, 인용문헌): _Judged}.

끝 상태는 셋이다 (design 5절):
- 근거 문단을 냄 -> 지금처럼 대비 줄 근거 (compare가 다시 판정하거나, 판정까지 에이전트가 맡음)
- give_up / 새 후보·근거 0개 -> 판정은 1차 그대로, "조회 범위 내 없음" + 찾아본 범위
  (방식·질의·이유), 보류 없음
- 상한·호출 실패·검색 실패 -> 판정은 1차 그대로 + 그 구성요소만 보류
  `f3_compare:<unit_id>:claim<N>:recheck:e<n>:<인용문헌>:<limit_reached|call_failed|tool_failed>`

예외는 (구성요소 × 인용문헌)마다 여기서 잡는다. 그래서 묶음 단위 잡기(compare_unit)까지 올라가
1차 대비표를 버리는 일이 없다. 프로그래밍 오류·설정 오류는 잡지 않는다.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field

from patent_ai.core.agents.tool_loop import LoopStep, RecheckToolFailed
from patent_ai.core.bundle_errors import BUNDLE_ERRORS, CALL_FAILED, LIMIT_REACHED, TOOL_FAILED
from patent_ai.core.f3_claim_compare.citations import ResolvedCitation
from patent_ai.core.f3_claim_compare.compare import (
    _ask,
    _Candidate,
    _Collected,
    _compare_step,
    _hold,
    _Item,
    _Judged,
    _scope_text,
    _View,
)
from patent_ai.core.f3_claim_compare.inputs import F3Config, F3Settings
from patent_ai.core.f3_claim_compare.recheck.agent import AgentRun, run_cite_agent
from patent_ai.core.f3_claim_compare.recheck.fixed_loop import fixed_loop_candidates
from patent_ai.core.f3_claim_compare.recheck.tools import QUERY_MAX, SUBMIT_MAX, Submitted
from patent_ai.core.f3_claim_compare.result import RecheckLogRow, SearchLogRow
from patent_ai.core.f3_claim_compare.retry import confirmed, unverified
from patent_ai.core.f3_claim_compare.textmatch import find_span, is_too_short, text_hash
from patent_ai.core.llm.errors import ModelCallLimitExceeded
from patent_ai.core.llm.limits import RunContext
from patent_ai.core.schemas.common import Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.comparison import Judgment
from patent_ai.core.schemas.judgment_unit import JudgmentUnit
from patent_ai.retrieval.contract import Searcher
from patent_ai.retrieval.repository import ChunkRepository

logger = logging.getLogger(__name__)

# 보류 끝말 -> 다시 찾기 기록의 끝 상태 (에이전트 루프 끝말과 같은 이름)
_OUTCOME = {
    LIMIT_REACHED: "limit_reached",
    CALL_FAILED: "model_call_failed",
    TOOL_FAILED: "tool_failed",
}
_LOOP_FAILURES = {
    "limit_reached": LIMIT_REACHED,
    "model_call_failed": CALL_FAILED,
    "tool_failed": TOOL_FAILED,
}


class _Stopped(Exception):
    """에이전트 루프가 상한·실패로 끝났음 (예외로 바꿔 아래 한 자리에서 보류로 처리한다)."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


# 구성요소 × 인용문헌 하나에서 잡는 예외 (design 4-4). 프로그래밍 오류는 잡지 않는다
_STOPPERS = (*BUNDLE_ERRORS, RecheckToolFailed, _Stopped)


def _kind_of(error: Exception) -> str:
    """예외 -> 보류 끝말. 상한은 실패가 아니라 limit_reached (임베딩 상한 포함)."""
    if isinstance(error, _Stopped):
        return error.kind
    if isinstance(error, ModelCallLimitExceeded):
        return LIMIT_REACHED
    if isinstance(error, RecheckToolFailed):
        return TOOL_FAILED
    return CALL_FAILED  # ModelCallFailed·ModelOutputInvalid


@dataclass
class _Trace:
    """구성요소 × 인용문헌 하나의 진행 기록 (중간에 실패해도 여기까지는 다시 찾기 기록에 남는다)."""

    queries: list[str] = field(default_factory=list)
    tool_calls: int = 0
    turns: int = 0
    steps: list[LoopStep] = field(default_factory=list)
    submitted_ids: list[str] = field(default_factory=list)
    reason: str | None = None
    outcome: str = "submitted"


def _recorded_step(step: LoopStep) -> dict:
    """F3 결과와 DB 단계 기록에 공통으로 남길 도구 입력만 골라 길이를 제한한다."""
    raw = step.logged_input
    tool_input = {}
    for key in ("query", "paragraph_id", "judgment", "reason"):
        if key in raw:
            tool_input[key] = raw[key][:QUERY_MAX]
    if "k" in raw:
        tool_input["k"] = raw["k"]
    if "paragraph_ids" in raw:
        tool_input["paragraph_ids"] = [pid[:QUERY_MAX] for pid in raw["paragraph_ids"][:SUBMIT_MAX]]
    return {
        "turn": step.turn,
        "tool_name": step.tool_name,
        "tool_input": tool_input,
        "result_ids": step.result_ids,
        "is_error": step.is_error,
    }


def _asked(queries: list[str]) -> str:
    return ", ".join(queries) if queries else "없음"


def _scope(
    cite: ResolvedCitation,
    settings: F3Settings,
    mode: str,
    queries: list[str],
    give_up: str | None = None,
) -> str:
    """다시 찾아본 범위 글: 1차 범위 + 다시 찾기 방식·질의(·give_up 이유)."""
    tail = f", give_up 이유 {give_up}" if give_up else ""
    return f"{_scope_text(cite, settings)} · 다시 찾기({mode}): 질의 {_asked(queries)}{tail}"


def _finish(one: _Judged, scope: str, mode: str, queries: list[str]) -> _Judged:
    """끝까지 돈 다시 찾기 결과에 찾아본 범위와 근거 줄 앞말을 붙인다."""
    one.scope = scope
    one.why_prefix = f"다시 찾기({mode}). 질의: {_asked(queries)}. "
    # 에이전트가 낸 조각 순서는 검색 순위가 아니다 (고정 루프는 실제 검색 순위라 그대로)
    one.rank_words = mode != "agent"
    return one


# ---- agent ----
def _log_agent_search(
    unit: JudgmentUnit,
    view: _View,
    item: _Item,
    cite: ResolvedCitation,
    run: AgentRun,
    scope: str,
    seen: _Collected,
) -> None:
    """에이전트 대화의 검색 결과를 검색 기록 2차(round=2) 한 줄로 남긴다 (채점기 search_recall)."""
    hits = run.toolbox.hits
    outcome = run.loop.outcome
    if hits:
        status = confirmed("다시 찾기 검색 결과를 받음")
    elif not run.loop.queries:
        # 성공한 검색이 0번: 다시 찾기는 찾아보지 않았으니 "없음"이라 쓰지 않는다
        status = unverified(UnverifiedReason.NOT_EXTRACTED)
    elif outcome in ("submitted", "gave_up"):
        status = Status(value=StatusValue.NOT_FOUND_IN_SCOPE, searched_scope=scope)
    else:  # 끝까지 못 봄: 없다고 쓰지 않는다
        reason = (
            UnverifiedReason.LIMIT_REACHED
            if outcome == "limit_reached"
            else UnverifiedReason.NOT_EXTRACTED
        )
        status = unverified(reason)
    e = item.e
    seen.search_log.append(
        SearchLogRow(
            unit_id=unit.unit_id,
            claim=view.claim,
            element_claim=e.claim,
            element_no=e.no,
            element_hash=text_hash(e.text),
            citation=cite.label,
            doc_id=cite.doc_id,
            round=2,
            status=status,
            searched_scope=scope,
            hit_chunk_ids=list(hits),
        )
    )


def _judge_by_agent(
    sub: Submitted,
    cands: Mapping[str, _Candidate],
    first: Judgment,
    min_chars: int,
) -> _Judged:
    """에이전트가 낸 판정·quote를 조각 글과 대조한다 (맞지 않거나 너무 짧은 quote는 버림)."""
    picks: list[tuple[_Candidate, str]] = []
    dropped = 0
    for it in sub.items:
        cand = cands[it.paragraph_id]
        span = find_span(it.quote, cand.chunk.text)
        if span is None or is_too_short(it.quote, cand.chunk.text, min_chars):
            dropped += 1
            continue
        picks.append((cand, cand.chunk.text[span[0] : span[1]]))
    return _Judged(sub.judgment or first, picks, dropped)


def _agent_pair(
    unit: JudgmentUnit,
    view: _View,
    item: _Item,
    cite: ResolvedCitation,
    shown: Mapping[str, _Candidate],
    first: Judgment,
    config: F3Config,
    ctx: RunContext,
    searcher: Searcher,
    repo: ChunkRepository,
    seen: _Collected,
    trace: _Trace,
) -> _Judged:
    settings, recheck = config.settings, config.recheck
    key = (item.n, cite.label)
    run = run_cite_agent(
        element=item.e,
        claim_text=view.claim_text,
        cite=cite,
        shown=set(shown),
        settings=settings,
        recheck=recheck,
        ctx=ctx,
        searcher=searcher,
        repo=repo,
    )
    loop = run.loop
    trace.queries = list(loop.queries)
    trace.tool_calls, trace.turns, trace.outcome = loop.tool_calls, loop.turns, loop.outcome
    trace.steps = loop.steps
    give_up = getattr(loop.value, "reason", None) if loop.outcome == "gave_up" else None
    scope = _scope(cite, settings, "agent", trace.queries, give_up)
    _log_agent_search(unit, view, item, cite, run, scope, seen)
    if loop.outcome in _LOOP_FAILURES:
        raise _Stopped(_LOOP_FAILURES[loop.outcome])
    if loop.outcome == "gave_up":
        # 판정은 1차 그대로, 조회 범위 내 없음 + 찾아본 범위. 보류하지 않는다
        trace.reason = give_up
        return _finish(_Judged(first), scope, "agent", trace.queries)

    sub = loop.value
    assert isinstance(sub, Submitted)
    trace.submitted_ids = list(sub.paragraph_ids)
    cands: dict[str, _Candidate] = {}
    for rank, pid in enumerate(sub.paragraph_ids, start=1):
        chunk = run.toolbox.get_chunk(pid)
        assert chunk is not None  # 도구가 제출 때 이미 검사했다
        cand = _Candidate(chunk, cite.label)
        cand.ranks[item.n] = rank  # 낸 순서를 순위로 (recall 프롬프트의 구성요소별 묶음용)
        cands[pid] = cand
    if recheck.recheck_judge == "compare":
        # 낸 조각만 후보로 compare가 다시 판정한다 (구성요소 × 인용문헌마다 1번)
        again = _ask(
            view.claim,
            view.claim_text,
            [item],
            [key],
            cands,
            settings.min_quote_chars,
            ctx,
            _compare_step(settings),
        )
        one = again.get(key) or _Judged(first)
    else:
        one = _judge_by_agent(sub, cands, first, settings.min_quote_chars)
    return _finish(one, scope, "agent", trace.queries)


# ---- fixed_loop ----
def _fixed_pair(
    unit: JudgmentUnit,
    view: _View,
    item: _Item,
    cite: ResolvedCitation,
    shown: Mapping[str, _Candidate],
    first: Judgment,
    config: F3Config,
    ctx: RunContext,
    searcher: Searcher,
    seen: _Collected,
    trace: _Trace,
) -> _Judged:
    settings = config.settings
    key = (item.n, cite.label)
    trace.turns = 1  # 질의 다시 쓰기 모델 호출 한 번
    found = fixed_loop_candidates(
        unit_id=unit.unit_id,
        claim=view.claim,
        item_n=item.n,
        element=item.e,
        claim_text=view.claim_text,
        cite=cite,
        shown=shown,
        settings=settings,
        recheck=config.recheck,
        ctx=ctx,
        searcher=searcher,
        search_log=seen.search_log,
        queries_out=trace.queries,
        steps_out=trace.steps,
    )
    scope = _scope(cite, settings, "fixed_loop", trace.queries)
    trace.submitted_ids = list(found)
    if not found:
        trace.outcome, trace.reason = "gave_up", "no_new_candidates"
        return _finish(_Judged(first), scope, "fixed_loop", trace.queries)
    again = _ask(
        view.claim,
        view.claim_text,
        [item],
        [key],
        found,
        settings.min_quote_chars,
        ctx,
        _compare_step(settings),
    )
    return _finish(again.get(key) or _Judged(first), scope, "fixed_loop", trace.queries)


# ---- 진입 ----
def recheck_missing(
    unit: JudgmentUnit,
    view: _View,
    missing: list[tuple[_Item, ResolvedCitation]],
    first: Mapping[tuple[int, str], Judgment],
    shown: Mapping[str, _Candidate],
    config: F3Config,
    ctx: RunContext,
    searcher: Searcher,
    repo: ChunkRepository,
    seen: _Collected,
) -> dict[tuple[int, str], _Judged]:
    """못 찾은 (구성요소, 인용문헌)마다 다시 찾는다. `_second_round`와 같은 입출력.

    (구성요소 × 인용문헌)마다 따로 돌고 따로 실패한다: 한 곳이 상한·실패로 끝나도 그 구성요소만
    보류하고 다른 구성요소 결과는 건드리지 않는다.
    """
    recheck = config.recheck
    mode = recheck.recheck
    assert mode in ("fixed_loop", "agent")  # none은 compare.py가 이 함수를 부르지 않는다
    if mode == "fixed_loop" and recheck.recheck_judge != "compare":
        # 판정까지 에이전트가 맡는 것은 agent 방식뿐이다: 고정 루프는 늘 compare가 판정한다
        logger.warning(
            "recheck fixed_loop: recheck_judge %s는 무시하고 compare로 판정", recheck.recheck_judge
        )
    judge = recheck.recheck_judge if mode == "agent" else "compare"
    out: dict[tuple[int, str], _Judged] = {}
    for item, cite in missing:
        key = (item.n, cite.label)
        trace = _Trace()
        try:
            if mode == "agent":
                one = _agent_pair(
                    unit,
                    view,
                    item,
                    cite,
                    shown,
                    first[key],
                    config,
                    ctx,
                    searcher,
                    repo,
                    seen,
                    trace,
                )
            else:
                one = _fixed_pair(
                    unit, view, item, cite, shown, first[key], config, ctx, searcher, seen, trace
                )
        except _STOPPERS as e:
            # 끝까지 못 봄: 판정은 1차 그대로 두고 이 구성요소만 보류한다
            kind = _kind_of(e)
            trace.outcome = _OUTCOME[kind]
            trace.reason = None if isinstance(e, _Stopped) else type(e).__name__
            one = _Judged(first[key])
            task = (
                f"f3_compare:{unit.unit_id}:claim{view.claim}:recheck:e{item.n}:{cite.label}:{kind}"
            )
            logger.warning("recheck %s: %s (이 구성요소만 보류)", task, trace.outcome)
            _hold(
                seen,
                task,
                f"{cite.label} 다시 찾기({mode})를 끝내지 못함 ({kind}). "
                f"찾아본 질의 {_asked(trace.queries)}",
            )
        out[key] = one
        e = item.e
        seen.recheck.append(
            RecheckLogRow(
                unit_id=unit.unit_id,
                claim=view.claim,
                element_claim=e.claim,
                element_no=e.no,
                citation=cite.label,
                doc_id=cite.doc_id,
                mode=mode,
                judge=judge,
                outcome=trace.outcome,
                tool_calls=len(trace.steps) if mode == "fixed_loop" else trace.tool_calls,
                turns=trace.turns,
                queries=trace.queries,
                submitted_ids=trace.submitted_ids,
                reason=trace.reason,
                steps=[_recorded_step(step) for step in trace.steps],
            )
        )
    return out
