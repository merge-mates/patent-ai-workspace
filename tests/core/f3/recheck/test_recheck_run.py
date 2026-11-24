"""(가) 자리 잇기 테스트: recheck none / fixed_loop / agent (이슈 #309, 계획 m3-i2-309b task-4).

기대값은 task 항목과 design 2·3(가)·4-4·5절, D11: none이면 지금 second_search 그대로, none이 아니면
second_search는 안 돎, 근거 0개 구성요소만 다시 찾음, 구성요소 × 인용문헌마다 예외를 잡아 그
구성요소만 보류(1차 대비표 그대로), 끝 상태 셋(근거 / 조회 범위 내 없음 / 보류).
가짜 전송층 + 메모리 저장소만 쓴다 (네트워크·키 없음).
"""

import functools
import json

import pytest

from patent_ai.core.agents import step_inputs
from patent_ai.core.bundle_errors import held_error_status
from patent_ai.core.f3_claim_compare.compare import STEP, compare_unit, make_searcher
from patent_ai.core.f3_claim_compare.config import load_f3_settings
from patent_ai.core.f3_claim_compare.inputs import F3Config, F3Inputs
from patent_ai.core.f3_claim_compare.recheck.config import (
    RecheckLimits,
    RecheckSearch,
    RecheckSettings,
)
from patent_ai.core.f3_claim_compare.result import F3Result
from patent_ai.core.f3_claim_compare.run import _held_status
from patent_ai.core.f3_claim_compare.units import build_units
from patent_ai.core.llm.errors import ModelCallFailed, ModelCallLimitExceeded
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import ConverseResponse, FakeTransport, TransportResponse
from patent_ai.core.schemas.common import StatusValue, UnverifiedReason
from patent_ai.core.schemas.comparison import Judgment, ParagraphSource
from patent_ai.retrieval.repository import InMemoryChunkRepository
from tests.core.f3.fakes import OK, chunk, citation, oa, paragraph, rejection, split

AGENT = "recheck.agent"
REWRITE = "recheck.rewrite"
D1 = "KR20990000001A"
SENSOR, TANK = "흙의 습도를 재는 습도 센서", "물을 담는 물통"
CLAIMS = {1: f"화분에 있어서, {SENSOR}; 및 {TANK}을 포함하는 화분."}
SPLITS = {1: split(1, [SENSOR, TANK])}
CHUNKS = [
    paragraph(D1, 23, "습도 센서는 흙에 꽂혀 습도를 잰다", [1.0, 0.0]),
    paragraph(D1, 31, "물통은 물을 담아 둔다", [0.0, 1.0]),
    paragraph(D1, 40, "뚜껑 아래 수조가 있다", [0.5, 0.5]),
    chunk(D1, "fig4", "도 4는 화분의 단면도", [0.2, 0.1], kind="figure", label="도 4", figures=[4]),
]
P23, P31, P40, FIG4 = (c.chunk_id for c in CHUNKS)
REPO = InMemoryChunkRepository({"cite": CHUNKS})
RESULT = oa([rejection(1, "29-2", [1], [citation("D1", D1)])])
FIRST_SCOPE = "D1 조각 4개 중 hybrid 상위 1 (cite-idx-v5)"
TEXT40 = "뚜껑 아래 수조가 있다"


@functools.cache
def _inner():
    return make_searcher(
        load_f3_settings(), REPO, lambda q: [1.0, 0.0] if "센서" in q else [0.0, 1.0]
    )


class _Searcher:
    """부른 검색을 기록하고, 질의별로 예외를 터뜨릴 수 있는 검색기 (모든 길이 이 객체 하나)."""

    def __init__(self, boom: dict[str, Exception] | None = None):
        self.calls: list[tuple[str, int]] = []
        self.boom = boom or {}

    def search(self, query, corpus, mode, k, doc_ids=None, as_of=None, **kw):
        self.calls.append((query, k))
        if query in self.boom:
            raise self.boom[query]
        return _inner().search(query, corpus, mode, k, doc_ids=doc_ids, as_of=as_of, **kw)


def _answer(*rows, claim=1) -> TransportResponse:
    made = [
        {
            "element_no": no,
            "citation": "D1",
            "judgment": judgment,
            "evidence": [{"chunk_id": c, "quote": q} for c, q in evidence],
        }
        for no, judgment, *evidence in rows
    ]
    return TransportResponse(
        json.dumps({"claim": claim, "rows": made}, ensure_ascii=False), 100, 50
    )


# 1차: 센서는 근거 있음, 물통은 못 고름 (근거 0개)
FIRST = _answer(
    (1, "disclosed", (P23, "습도 센서는 흙에 꽂혀 습도를 잰다")), (2, "difference_candidate")
)
FOUND40 = _answer((2, "disclosed", (P40, TEXT40)))


def use(name, input_, id_="tu_1"):
    return {"type": "tool_use", "id": id_, "name": name, "input": input_}


def reply(*blocks):
    return ConverseResponse(list(blocks), 100, 10, "tool_use")


def _search_turn(query="수조", k=3):
    return reply(use("search_vector", {"query": query, "k": k}))


def _found_turns(judge="compare", quote=TEXT40):
    """검색 -> 열기 -> 제출 세 차례."""
    if judge == "compare":
        submit = use("submit_evidence", {"paragraph_ids": [P40], "why": "물통을 수조로 적음"})
    else:
        submit = use(
            "submit_evidence",
            {
                "items": [{"paragraph_id": P40, "quote": quote}],
                "judgment": "disclosed",
                "why": "물통을 수조로 적음",
            },
        )
    return [_search_turn(), reply(use("open_paragraph", {"paragraph_id": P40})), reply(submit)]


def _give_up_turns(reason="not_in_document"):
    return [_search_turn(), reply(use("give_up", {"reason": reason, "tried": "수조 검색"}))]


def _rewrite(queries) -> TransportResponse:
    return TransportResponse(json.dumps({"queries": queries}, ensure_ascii=False), 100, 50)


def _settings(recheck="agent", judge="compare", **extra) -> RecheckSettings:
    return RecheckSettings(recheck=recheck, recheck_judge=judge, **extra)


def _run(
    recheck,
    responses,
    *,
    second_search=True,
    searcher=None,
    result=RESULT,
    splits=SPLITS,
    claims=CLAIMS,
    prefill=None,
):
    """recheck=None이면 recheck 칸을 아예 안 준다 (옛 설정 그대로)."""
    settings = load_f3_settings()
    settings = settings.model_copy(
        update={
            "second_search": second_search,
            "second_search_depth": 2,
            "search": settings.search.model_copy(update={"k": 1}),
        }
    )
    inputs = F3Inputs(claims_at_oa=claims, claims_status=OK, claims_document_id="d_c")
    extra = {} if recheck is None else {"recheck": recheck}
    config = F3Config(settings=settings, inputs=inputs, **extra)
    transport = FakeTransport(responses)
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    for step, n in (prefill or {}).items():  # 이미 n번 부른 것으로 센다
        for _ in range(n):
            ctx.budget.add(ctx.run_id, step, 1)
    searcher = searcher or _Searcher()
    units, _ = build_units(result, splits)
    out = compare_unit(units[0], result, splits, config, ctx=ctx, searcher=searcher, repo=REPO)
    return out, transport, searcher, units[0].unit_id


def _row(out, element):
    (row,) = [r for r in out.tables[0].rows if r.element == element]
    return row


def _baseline():
    """1차만 (recheck·second_search 둘 다 끔): 다시 찾기가 실패해도 이 표가 그대로 남아야 한다."""
    out, *_ = _run(None, {STEP: [FIRST]}, second_search=False)
    return out


def _rechecked_holds(out):
    """다시 찾기가 남긴 보류만 (명세서 없음 같은 다른 보류는 이 테스트와 상관없다)."""
    return [h for h in out.held_tasks if ":recheck:" in h.task]


def _task(unit_id, kind):
    return f"f3_compare:{unit_id}:claim1:recheck:e2:D1:{kind}"


def _compare_calls(transport):
    return [c for c in transport.calls if c["step"] == STEP]


# ---- none: 지금 그대로 ----
def test_none이면_지금_second_search_그대로다():
    responses = {STEP: [FIRST, FOUND40]}
    old, _, old_searches, _ = _run(None, responses)
    new, _, searches, _ = _run(_settings("none"), {STEP: [FIRST, FOUND40]})
    assert new.tables == old.tables and new.search_log == old.search_log
    assert new.held_tasks == old.held_tasks and new.recheck_log == []
    assert searches.calls == old_searches.calls == [(SENSOR, 1), (TANK, 1), (TANK, 2)]
    assert "두 번째 검색" in _row(new, TANK).why_retrieved


# ---- 검색기 하나가 1차(hybrid)와 에이전트 도구(bm25·vector)를 다 받는다 ----
def test_make_searcher는_설정_구현_외에_bm25_vector_방식도_받는다():
    searcher = _inner()
    for mode in ("hybrid", "bm25", "vector"):
        result = searcher.search("수조", "cite", mode, 3, doc_ids=[D1])
        assert result.mode == mode and result.hits


# ---- agent + compare ----
def test_agent면_second_search는_돌지_않고_구성요소의_근거는_낸_조각으로_다시_판정한다():
    responses = {STEP: [FIRST, FOUND40], AGENT: _found_turns()}
    out, transport, searcher, unit_id = _run(_settings(), responses, second_search=True)
    # 1차 둘 + 에이전트 검색 하나. second_search의 (물통, 상위 2)는 없다
    assert searcher.calls == [(SENSOR, 1), (TANK, 1), ("수조", 3)]
    calls = _compare_calls(transport)
    assert len(calls) == 2
    again = calls[1]["prompt"]
    assert TEXT40 in again and "물통은 물을 담아 둔다" not in again
    assert "단면도" not in again  # second_search의 도면 설명 조각이 끼지 않는다
    row = _row(out, TANK)
    assert row.judgment == Judgment.DISCLOSED and row.status.value == StatusValue.CONFIRMED
    assert [e.chunk_id for e in row.evidence] == [P40]
    assert row.paragraph_source == ParagraphSource.AI_FOUND
    assert row.why_retrieved.startswith("다시 찾기(agent). 질의: 수조")
    # 리뷰 답(#329): 에이전트가 낸 순서는 검색 순위가 아니라서 "N위"를 쓰지 않는다
    assert "1위" not in row.why_retrieved
    assert "구성요소 글자를 질의로 검색" not in row.why_retrieved
    # 근거가 있던 구성요소는 그대로
    sensor = _row(out, SENSOR)
    assert [e.chunk_id for e in sensor.evidence] == [P23]
    assert "다시 찾기" not in (sensor.why_retrieved or "")
    assert _rechecked_holds(out) == []


def test_다시_찾는_것은_근거가_0개인_구성요소뿐이다():
    responses = {STEP: [FIRST, FOUND40], AGENT: _found_turns()}
    out, transport, _, _ = _run(_settings(), responses)
    assert [r.element_no for r in out.recheck_log] == [2]
    # 에이전트 대화는 한 번 (첫 차례 system에 그 구성요소 글자가 있다)
    first_turns = [c for c in transport.calls if c["step"] == AGENT and len(c["messages"]) == 1]
    assert len(first_turns) == 1
    system = first_turns[0]["system"]
    asked = system.split("다시 찾을 구성요소")[1]  # 청구항 글(참고)에는 둘 다 있다
    assert TANK in asked and SENSOR not in asked
    assert "D1" in first_turns[0]["system"] and "4개" in first_turns[0]["system"]
    assert "판정까지 냅니다" not in first_turns[0]["system"]  # judge=compare면 judge_note 없음


def test_1차에서_다_찾았으면_다시_찾지_않는다():
    both = _answer(
        (1, "disclosed", (P23, "습도 센서는 흙에 꽂혀 습도를 잰다")),
        (2, "disclosed", (P31, "물통은 물을 담아 둔다")),
    )
    out, transport, searcher, _ = _run(_settings(), {STEP: [both]})
    assert len(searcher.calls) == 2 and out.recheck_log == []
    assert all(r.round == 1 for r in out.search_log)
    assert [c["step"] for c in transport.calls] == [STEP]


def test_agent의_검색_결과는_검색_기록_2차_한_줄로_남는다():
    responses = {STEP: [FIRST, FOUND40], AGENT: _found_turns()}
    out, *_ = _run(_settings(), responses)
    assert [(r.round, r.element_no) for r in out.search_log] == [(1, 1), (1, 2), (2, 2)]
    second = out.search_log[2]
    assert (second.citation, second.doc_id, second.unit_id, second.claim) == (
        "D1",
        D1,
        out.tables[0].unit_id,
        1,
    )
    assert P40 in second.hit_chunk_ids
    assert second.status.value == StatusValue.CONFIRMED
    assert "다시 찾기(agent)" in second.searched_scope


def test_2차_검색_기록이_채점기_search_recall에_잡힌다():
    from eval.f3.pred import F3Pred
    from eval.f3.score import _chunk_ids, rechecked_rows_of

    responses = {STEP: [FIRST, FOUND40], AGENT: _found_turns()}
    out, *_ = _run(_settings(), responses)
    result = F3Result(
        oa_id="oa_1",
        units=build_units(RESULT, SPLITS)[0],
        comparisons=out.tables,
        search_log=out.search_log,
        recheck_log=out.recheck_log,
        status=out.tables[0].status,
    )
    pred = F3Pred.model_validate_json(result.model_dump_json())
    searched, selected, _, _ = _chunk_ids(pred, 1, 1, D1)
    assert P40 in searched and P40 in selected
    assert rechecked_rows_of({"oa_1_1": pred})  # 2차 줄이 있는 줄로 센다


def test_recheck_log_줄은_도구_호출_줄을_담고_원문_글은_없다():
    responses = {STEP: [FIRST, FOUND40], AGENT: _found_turns()}
    out, *_ = _run(_settings(), responses)
    (row,) = out.recheck_log
    assert (row.unit_id, row.claim, row.element_claim, row.element_no) == (
        out.tables[0].unit_id,
        1,
        1,
        2,
    )
    assert (row.citation, row.doc_id, row.mode, row.judge) == ("D1", D1, "agent", "compare")
    assert (row.outcome, row.tool_calls, row.turns) == ("submitted", 3, 3)
    assert row.queries == ["수조"] and row.submitted_ids == [P40] and row.reason is None
    assert [s["tool_name"] for s in row.steps] == [
        "search_vector",
        "open_paragraph",
        "submit_evidence",
    ]
    first = row.steps[0]
    assert set(first) == {"turn", "tool_input", "tool_name", "result_ids", "is_error"}
    assert first["turn"] == 1 and first["tool_input"] == {"query": "수조", "k": 3}
    assert P40 in first["result_ids"] and first["is_error"] is False
    assert row.steps[2]["tool_input"] == {"paragraph_ids": [P40]}
    dumped = json.dumps(row.model_dump(), ensure_ascii=False)
    assert TEXT40 not in dumped and "물통을 수조로 적음" not in dumped  # 문단 글·why 없음


def test_recheck_log는_F3Result_기본값이_빈_목록이다():
    result = F3Result(oa_id="x", status=OK)
    assert result.recheck_log == []


# ---- agent + agent (판정까지) ----
def test_판정까지_agent면_quote를_대조해_근거로_받고_compare는_다시_부르지_않는다():
    responses = {STEP: [FIRST], AGENT: _found_turns("agent")}
    out, transport, _, _ = _run(_settings(judge="agent"), responses)
    assert len(_compare_calls(transport)) == 1
    row = _row(out, TANK)
    assert row.judgment == Judgment.DISCLOSED and row.status.value == StatusValue.CONFIRMED
    assert [(e.chunk_id, e.raw_text) for e in row.evidence] == [(P40, TEXT40)]
    assert row.why_retrieved.startswith("다시 찾기(agent). 질의: 수조")
    (log,) = out.recheck_log
    assert (log.judge, log.outcome, log.submitted_ids) == ("agent", "submitted", [P40])
    first = next(c for c in transport.calls if c["step"] == AGENT)
    assert "판정까지 냅니다" in first["system"]


def test_판정까지_agent일_때_quote가_너무_짧으면_도구가_되돌려_주고_근거로_받지_않는다():
    # 도구가 F3와 같은 규칙으로 거절하고(오류 결과) 대화가 이어진다. 포기로 끝나면 근거는 없다
    turns = _found_turns("agent", quote="수조")[:2] + [_found_turns("agent", quote="수조")[2]]
    turns.append(reply(use("give_up", {"reason": "other", "tried": "수조"}, "tu_9")))
    out, transport, *_ = _run(_settings(judge="agent"), {STEP: [FIRST], AGENT: turns})
    row = _row(out, TANK)
    assert row.evidence == []
    last = json.dumps(transport.calls[-1]["messages"], ensure_ascii=False)
    assert "너무 짧다" in last
    assert [h.task for h in _rechecked_holds(out)] == []


# ---- give_up ----
def test_give_up이면_보류_없이_조회_범위_내_없음과_찾아본_범위가_남는다():
    out, transport, _, _ = _run(_settings(), {STEP: [FIRST], AGENT: _give_up_turns()})
    assert len(_compare_calls(transport)) == 1  # 다시 판정하지 않는다
    row = _row(out, TANK)
    assert row.judgment == Judgment.DIFFERENCE_CANDIDATE and row.evidence == []
    assert row.status.value == StatusValue.NOT_FOUND_IN_SCOPE
    scope = row.status.searched_scope
    assert scope.startswith(FIRST_SCOPE)
    assert "다시 찾기(agent)" in scope and "질의 수조" in scope
    assert "give_up 이유 not_in_document" in scope
    assert _rechecked_holds(out) == []
    (log,) = out.recheck_log
    assert (log.outcome, log.reason, log.queries) == ("gave_up", "not_in_document", ["수조"])
    assert out.tables[0].status.value == StatusValue.NOT_FOUND_IN_SCOPE


def test_거절된_검색만_하고_give_up이면_2차_검색_기록을_조회_범위_내_없음으로_쓰지_않는다():
    # 리뷰 막음(#329): k 범위 밖이라 검색하지 않았는데 "질의 수조"·not_found_in_scope로 남으면
    # 검색에서 못 찾음 ≠ 없음 원칙을 어긴다. 대비 줄은 1차 결과(1차는 실제로 검색함)를 그대로 둔다
    turns = [
        _search_turn(k=99),
        reply(use("give_up", {"reason": "other", "tried": "수조"}, "tu_2")),
    ]
    out, *_ = _run(_settings(), {STEP: [FIRST], AGENT: turns})
    assert out.recheck_log[0].queries == []
    second = [r for r in out.search_log if r.round == 2]
    assert second and all(r.status.value != StatusValue.NOT_FOUND_IN_SCOPE for r in second)
    assert "질의 수조" not in _row(out, TANK).status.searched_scope


def test_바로_give_up이어도_보류_없이_조회_범위_내_없음이다():
    turns = [reply(use("give_up", {"reason": "other", "tried": "없음"}))]
    out, *_ = _run(_settings(), {STEP: [FIRST], AGENT: turns})
    assert _row(out, TANK).status.value == StatusValue.NOT_FOUND_IN_SCOPE
    assert _rechecked_holds(out) == [] and out.recheck_log[0].queries == []


# ---- 상한·실패: 그 구성요소만 보류, 1차 대비표 그대로 ----
def test_도구_호출_상한에_닿으면_limit_reached로_그_구성요소만_보류한다():
    limits = RecheckLimits(tool_calls=1, turns=10)
    turns = [_search_turn("수조"), _search_turn("저장 용기")]
    out, transport, _, unit_id = _run(_settings(limits=limits), {STEP: [FIRST], AGENT: turns})
    (held,) = _rechecked_holds(out)
    assert held.task == _task(unit_id, "limit_reached")
    assert "찾아본 질의 수조" in held.waiting_for
    assert held_error_status(held.task).reason == UnverifiedReason.LIMIT_REACHED
    assert out.tables == _baseline().tables  # 1차 대비표 그대로
    assert out.call_errors == [] and out.units_tried == 1
    assert _row(out, TANK).status.searched_scope == FIRST_SCOPE
    assert out.recheck_log[0].outcome == "limit_reached" and out.recheck_log[0].queries == ["수조"]
    assert len(_compare_calls(transport)) == 1


def test_에이전트_모델_호출이_실패하면_call_failed로_그_구성요소만_보류한다():
    responses = {STEP: [FIRST], AGENT: [ModelCallFailed("끊김")]}
    out, _, _, unit_id = _run(_settings(), responses)
    assert [h.task for h in _rechecked_holds(out)] == [_task(unit_id, "call_failed")]
    assert out.tables == _baseline().tables
    assert out.call_errors == [] and out.units_tried == 1  # 묶음 단위 실패로 안 올라간다
    assert out.recheck_log[0].outcome == "model_call_failed"
    assert held_error_status(_rechecked_holds(out)[0].task).reason == UnverifiedReason.NOT_EXTRACTED


def test_다시_판정이_실패해도_그_구성요소만_보류하고_1차_표는_남는다():
    broken = TransportResponse("JSON 아님", 10, 10)
    responses = {STEP: [FIRST, broken, broken], AGENT: _found_turns()}
    out, _, _, unit_id = _run(_settings(), responses)
    assert [h.task for h in _rechecked_holds(out)] == [_task(unit_id, "call_failed")]
    assert out.tables == _baseline().tables and out.call_errors == []


def test_도구의_검색이_예외를_던지면_tool_failed이고_확인되지_않음_not_extracted다():
    searcher = _Searcher({"수조": RuntimeError("DB 끊김")})
    out, _, _, unit_id = _run(
        _settings(), {STEP: [FIRST], AGENT: [_search_turn()]}, searcher=searcher
    )
    (held,) = _rechecked_holds(out)
    assert held.task == _task(unit_id, "tool_failed")
    status = _held_status(held, "oa_1")
    assert (
        status.value == StatusValue.UNVERIFIED and status.reason == UnverifiedReason.NOT_EXTRACTED
    )
    assert out.tables == _baseline().tables and out.recheck_log[0].outcome == "tool_failed"


def test_질의_임베딩이_호출_상한에_닿으면_tool_failed가_아니라_limit_reached다():
    boom = {"수조": ModelCallLimitExceeded("max_model_calls", 1200, 1200)}
    out, _, _, unit_id = _run(
        _settings(), {STEP: [FIRST], AGENT: [_search_turn()]}, searcher=_Searcher(boom)
    )
    assert [h.task for h in _rechecked_holds(out)] == [_task(unit_id, "limit_reached")]
    assert out.recheck_log[0].outcome == "limit_reached"


def test_실행_합계_상한에_닿아도_limit_reached_보류이고_표는_남는다():
    out, _, _, unit_id = _run(
        _settings(), {STEP: [FIRST], AGENT: _found_turns()}, prefill={AGENT: 400}
    )
    assert [h.task for h in _rechecked_holds(out)] == [_task(unit_id, "limit_reached")]
    assert out.tables == _baseline().tables


# ---- fixed_loop ----
def test_fixed_loop_평소는_다시_쓴_질의로_찾아_compare가_다시_판정한다():
    responses = {STEP: [FIRST, FOUND40], REWRITE: [_rewrite(["수조"])]}
    out, transport, searcher, _ = _run(_settings("fixed_loop"), responses)
    assert searcher.calls == [(SENSOR, 1), (TANK, 1), ("수조", 10)]  # second_search는 안 돈다
    assert len(_compare_calls(transport)) == 2
    row = _row(out, TANK)
    assert [e.chunk_id for e in row.evidence] == [P40]
    assert row.why_retrieved.startswith("다시 찾기(fixed_loop). 질의: 수조")
    assert [(r.round, r.element_no) for r in out.search_log] == [(1, 1), (1, 2), (2, 2)]
    (log,) = out.recheck_log
    assert (log.mode, log.judge, log.outcome, log.queries) == (
        "fixed_loop",
        "compare",
        "submitted",
        ["수조"],
    )
    assert log.tool_calls == 1
    assert log.steps == [
        {
            "turn": 1,
            "tool_name": "search_hybrid",
            "tool_input": {"query": "수조", "k": 10},
            "result_ids": [P40, P31, FIG4, P23],
            "is_error": False,
        }
    ]
    assert _rechecked_holds(out) == []


def test_fixed_loop의_검색이_예외를_던지면_그_구성요소만_tool_failed이고_1차_대비표는_남는다():
    # 리뷰 막음(#329): 방식과 상관없이 그 구성요소만 tool_failed 보류 (requirements)
    searcher = _Searcher({"끊긴 질의": RuntimeError("DB 끊김")})
    responses = {STEP: [FIRST], REWRITE: [_rewrite(["수조", "끊긴 질의", "다음 질의"])]}
    out, _, _, unit_id = _run(_settings("fixed_loop"), responses, searcher=searcher)
    assert [h.task for h in _rechecked_holds(out)] == [_task(unit_id, "tool_failed")]
    assert out.tables == _baseline().tables
    (log,) = out.recheck_log
    assert log.tool_calls == 2
    assert [(s["tool_input"]["query"], s["is_error"]) for s in log.steps] == [
        ("수조", False),
        ("끊긴 질의", True),
    ]
    assert log.steps[-1]["result_ids"] == []


def test_fixed_loop에서_새_조각이_0개면_보류_없이_조회_범위_내_없음이다():
    search = RecheckSearch(k_max=10, snippet_chars=160, rewrite_k=1, rewrite_n=1)
    responses = {STEP: [FIRST], REWRITE: [_rewrite(["물통"])]}
    out, transport, _, _ = _run(_settings("fixed_loop", search=search), responses)
    assert len(_compare_calls(transport)) == 1
    row = _row(out, TANK)
    assert row.status.value == StatusValue.NOT_FOUND_IN_SCOPE
    assert "다시 찾기(fixed_loop): 질의 물통" in row.status.searched_scope
    assert _rechecked_holds(out) == []
    assert out.recheck_log[0].outcome == "gave_up"


def test_fixed_loop_다시_쓰기가_실패하면_그_구성요소만_보류한다():
    responses = {STEP: [FIRST], REWRITE: [ModelCallFailed("끊김")]}
    out, _, _, unit_id = _run(_settings("fixed_loop"), responses)
    assert [h.task for h in _rechecked_holds(out)] == [_task(unit_id, "call_failed")]
    assert out.tables == _baseline().tables and out.call_errors == []


def test_fixed_loop_다시_쓴_질의가_빈_글뿐이면_찾지_않고_call_failed로_보류한다():
    responses = {STEP: [FIRST], REWRITE: [_rewrite([" "])]}
    out, _, searcher, unit_id = _run(_settings("fixed_loop"), responses)
    assert [h.task for h in _rechecked_holds(out)] == [_task(unit_id, "call_failed")]
    assert [c[1] for c in searcher.calls] == [1, 1]  # 1차 검색 둘뿐, 다시 찾기 검색은 없다
    assert out.tables == _baseline().tables


def test_fixed_loop_호출_상한이면_limit_reached로_보류한다():
    responses = {STEP: [FIRST], REWRITE: [_rewrite(["수조"])]}
    out, _, _, unit_id = _run(_settings("fixed_loop"), responses, prefill={REWRITE: 200})
    assert [h.task for h in _rechecked_holds(out)] == [_task(unit_id, "limit_reached")]
    assert out.tables == _baseline().tables


# ---- 독립항 건너뜀 판단은 다시 찾은 뒤 결과로 ----
@pytest.mark.parametrize(
    "failure",
    [ModelCallFailed("끊김"), ModelCallLimitExceeded("f3.compare", 1, 1)],
)
def test_뒤_청구항_호출_실패나_상한에도_앞_청구항_다시_찾기_로그는_남는다(failure):
    claims = {
        **CLAIMS,
        3: "제1항에 있어서, 뚜껑을 더 포함하는 화분.",
    }
    splits = {**SPLITS, 3: split(3, ["뚜껑"], [1])}
    result = oa([rejection(1, "29-2", [1, 3], [citation("D1", D1)])])
    responses = {STEP: [FIRST, FOUND40, failure], AGENT: _found_turns()}
    out, transport, _, _ = _run(_settings(), responses, result=result, splits=splits, claims=claims)
    assert len(_compare_calls(transport)) == 3
    assert out.held_tasks
    (log,) = out.recheck_log
    assert log.claim == 1
    assert [s["tool_name"] for s in log.steps] == [
        "search_vector",
        "open_paragraph",
        "submit_evidence",
    ]


def test_다시_찾아_독립항이_무너지면_종속항을_건너뛰지_않고_대비한다():
    claims = {
        1: "화분에 있어서, 습도 센서; 및 물통을 포함하는 화분.",
        3: "제1항에 있어서, 뚜껑을 더 포함하는 화분.",
    }
    splits = {1: split(1, ["습도 센서", "물통"]), 3: split(3, ["뚜껑"], [1])}
    result = oa([rejection(1, "29-2", [1, 3], [citation("D1", D1)])])
    first = _answer(
        (1, "disclosed", (P23, "습도 센서는 흙에 꽂혀 습도를 잰다")), (2, "difference_candidate")
    )
    rejudged = _answer((2, "disclosed", (P31, "물통은 물을 담아 둔다")))
    lid = _answer((1, "difference_candidate"), claim=3)
    turns = [
        _search_turn("물통", 2),
        reply(use("open_paragraph", {"paragraph_id": P31})),
        reply(use("submit_evidence", {"paragraph_ids": [P31], "why": "같은 말"})),
        reply(use("give_up", {"reason": "other", "tried": "뚜껑"})),  # 종속항 구성요소는 못 찾음
    ]
    responses = {STEP: [first, rejudged, lid], AGENT: turns}
    out, transport, _, _ = _run(_settings(), responses, result=result, splits=splits, claims=claims)
    assert len(_compare_calls(transport)) == 3
    assert {r.claim for r in out.tables[0].rows} == {1, 3}
    assert all(not h.task.endswith(":dependent") for h in out.held_tasks)


# ---- 가짜 응답으로 run_case 한 바퀴 ----
def test_run_case_fixed_order에서_recheck_agent로_사건_하나가_succeeded로_끝난다(
    tmp_path, monkeypatch
):
    from tests.core.agents.test_fixed_order_f3_f4 import _go, _responses
    from tests.core.run_case_fakes import wire

    wire(monkeypatch)
    base, _ = _go(tmp_path)  # recheck: none 기준 한 바퀴

    monkeypatch.setattr(step_inputs, "load_recheck_settings", lambda *a, **k: _settings("agent"))
    responses = _responses()
    responses[AGENT] = [reply(use("give_up", {"reason": "not_in_document", "tried": "수조"}))]
    out, _ = _go(tmp_path, responses)
    assert out.state == "succeeded" and out.error is None and out.waiting_for is None
    assert out.trace == base.trace  # 새 멈춤·새 단계 없음
    assert set(out.results) == set(base.results)  # 결과 키 같음
    f3 = out.results["run_f3"]
    assert [r.outcome for r in f3.recheck_log] == ["gave_up"]
    assert not any(":recheck:" in h.task for h in f3.held_tasks)
    assert base.results["run_f3"].recheck_log == []
