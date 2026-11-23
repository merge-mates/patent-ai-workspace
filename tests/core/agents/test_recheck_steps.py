"""다시 찾기 도구 호출 줄이 단계 기록(StepRecord)으로 옮겨지는지 (이슈 #309). DB·키 없음."""

import json

from patent_ai.core.agents import step_inputs
from patent_ai.core.agents.steps import StepRecord
from patent_ai.core.f3_claim_compare import run as f3_run
from patent_ai.core.f3_claim_compare.recheck.config import RecheckSettings
from patent_ai.core.f3_claim_compare.recheck.tools import QUERY_MAX
from patent_ai.core.f3_claim_compare.result import RecheckLogRow
from tests.core.agents.test_fixed_order_f3_f4 import _go, _responses, wired  # noqa: F401
from tests.core.agents.test_tool_loop import reply, use
from tests.core.f3 import scenario

UNIT = "oa_1:29-2:c1"


def _log_row() -> RecheckLogRow:
    return RecheckLogRow(
        unit_id=UNIT,
        claim=1,
        element_claim=1,
        element_no=2,
        citation="D1",
        doc_id="d_cite",
        mode="agent",
        judge="compare",
        outcome="submitted",
        tool_calls=3,
        turns=3,
        steps=[
            {
                "turn": 1,
                "tool_name": "search_vector",
                "tool_input": {"query": "수조", "k": 3},
                "result_ids": ["p1", "p2"],
                "is_error": False,
            },
            {
                "turn": 2,
                "tool_name": "open_paragraph",
                "tool_input": {"paragraph_id": "p9"},
                "result_ids": [],
                "is_error": True,
            },
        ],
    )


def _with_recheck(monkeypatch):
    """진짜 run_f3 결과에 다시 찾기 기록 한 건을 얹는다 (다시 찾기 자체는 다른 테스트가 본다)."""
    real = f3_run.run_f3

    def wrapped(*a, **k):
        out = real(*a, **k)
        return out.model_copy(update={"recheck_log": [_log_row()]})

    monkeypatch.setattr(f3_run, "run_f3", wrapped)


def test_StepRecord_새_칸_기본값은_None이다():
    s = StepRecord(run_id="r", step_kind="code_tool", tool_name="x", reason="y", outcome="ok")
    assert s.unit_id is None and s.tool_input is None


def test_다시_찾기_도구_줄이_run_f3_뒤에_단계_기록으로_남는다(tmp_path, wired, monkeypatch):  # noqa: F811
    _with_recheck(monkeypatch)
    _, steps = _go(tmp_path)
    names = [r.tool_name for r in steps.records]
    i = names.index("run_f3")
    # run_f3 바로 뒤에 도구 호출 줄이 호출 순서대로, 그 다음은 run_f2
    assert names[i : i + 4] == [
        "run_f3",
        "recheck.search_vector",
        "recheck.open_paragraph",
        "run_f2",
    ]
    first, second = steps.records[i + 1], steps.records[i + 2]
    assert (first.step_kind, first.reason, first.outcome) == ("code_tool", "다시 찾기 도구", "ok")
    assert first.unit_id == UNIT and first.result_id == "p1,p2"
    where = {"claim": 1, "element_claim": 1, "element_no": 2, "citation": "D1"}
    assert first.tool_input == {"query": "수조", "k": 3, **where}
    assert second.outcome == "failed" and not second.result_id
    assert second.tool_input == {"paragraph_id": "p9", **where}


def test_청구항이_달라_구성요소_번호가_같아도_도구_줄을_가린다(tmp_path, wired, monkeypatch):  # noqa: F811
    # 한 묶음에 청구항 1·3: 둘 다 구성요소 1번이어도 claim·element_claim으로 가린다 (합격 기준 5)
    real = f3_run.run_f3
    one = _log_row().model_copy(update={"element_no": 1, "steps": _log_row().steps[:1]})
    three = one.model_copy(update={"claim": 3, "element_claim": 3})

    def wrapped(*a, **k):
        return real(*a, **k).model_copy(update={"recheck_log": [one, three]})

    monkeypatch.setattr(f3_run, "run_f3", wrapped)
    _, steps = _go(tmp_path)
    tools = [r for r in steps.records if r.tool_name.startswith("recheck.")]
    keys = {(r.unit_id, r.tool_input["claim"], r.tool_input["element_claim"]) for r in tools}
    assert keys == {(UNIT, 1, 1), (UNIT, 3, 3)}


def test_도구_줄에_원문_글_quote_why가_없다(tmp_path, wired, monkeypatch):  # noqa: F811
    # 실제 검색·열기·제출을 돌려 F3 결과와 그 결과에서 옮긴 단계 기록을 함께 본다.
    settings = RecheckSettings(recheck="agent", recheck_judge="agent")
    monkeypatch.setattr(step_inputs, "load_recheck_settings", lambda *a, **k: settings)
    pid = scenario.P31
    paragraph_text = scenario.CHUNKS[1].text
    why = "이 문장이 대비 근거인 이유"
    long_input = "가" * 1320 + "기록에서 제외할 끝부분"
    responses = _responses()
    responses["recheck.agent"] = [
        reply(use(long_input, {})),
        reply(use("search_vector", {"query": long_input, "k": 1})),
        reply(use("open_paragraph", {"paragraph_id": long_input})),
        reply(use("search_vector", {"query": "물통", "k": 1})),
        reply(use("open_paragraph", {"paragraph_id": pid})),
        reply(
            use(
                "submit_evidence",
                {
                    "items": [{"paragraph_id": pid, "quote": paragraph_text}],
                    "judgment": "disclosed",
                    "why": why,
                },
            )
        ),
        reply(use("give_up", {"reason": "not_in_document", "tried": "간격"})),
    ]
    out, steps = _go(tmp_path, responses)
    assert out.state == "succeeded"
    found = [
        r
        for r in steps.records
        if r.tool_name.startswith("recheck.") and r.tool_input["claim"] == 1
    ]
    assert [r.tool_name for r in found] == [
        "recheck.unknown_tool",
        "recheck.search_vector",
        "recheck.open_paragraph",
        "recheck.search_vector",
        "recheck.open_paragraph",
        "recheck.submit_evidence",
    ]
    assert [r.outcome for r in found] == ["failed"] * 3 + ["ok"] * 3
    assert found[1].tool_input["query"] == long_input[:QUERY_MAX]
    assert found[2].tool_input["paragraph_id"] == long_input[:QUERY_MAX]
    assert found[3].tool_input["query"] == "물통"
    assert found[4].result_id == found[5].result_id == pid
    assert found[5].tool_input["paragraph_ids"] == [pid]
    (log,) = [r for r in out.results["run_f3"].recheck_log if r.claim == 1]
    for rows in (log.steps, [r.model_dump() for r in found]):
        dumped = json.dumps(rows, ensure_ascii=False)
        assert all(
            text not in dumped
            for text in (paragraph_text, why, long_input[QUERY_MAX:], '"quote"', '"why"', '"text"')
        )


def test_다시_찾기_기록이_없으면_옛_줄_그대로다(tmp_path, wired):  # noqa: F811
    _, steps = _go(tmp_path)
    assert not any(r.tool_name.startswith("recheck.") for r in steps.records)
    assert all(r.unit_id is None and r.tool_input is None for r in steps.records)
