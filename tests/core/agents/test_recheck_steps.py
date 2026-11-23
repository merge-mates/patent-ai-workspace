"""다시 찾기 도구 호출 줄이 단계 기록(StepRecord)으로 옮겨지는지 (이슈 #309). DB·키 없음."""

import json

from patent_ai.core.agents.steps import StepRecord
from patent_ai.core.f3_claim_compare import run as f3_run
from patent_ai.core.f3_claim_compare.result import RecheckLogRow
from tests.core.agents.test_fixed_order_f3_f4 import _go, wired  # noqa: F401

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
    _with_recheck(monkeypatch)
    _, steps = _go(tmp_path)
    found = [r for r in steps.records if r.tool_name.startswith("recheck.")]
    assert found
    for r in found:
        dumped = json.dumps(r.model_dump(), ensure_ascii=False)
        assert "quote" not in dumped and "why" not in dumped and "text" not in dumped


def test_다시_찾기_기록이_없으면_옛_줄_그대로다(tmp_path, wired):  # noqa: F811
    _, steps = _go(tmp_path)
    assert not any(r.tool_name.startswith("recheck.") for r in steps.records)
    assert all(r.unit_id is None and r.tool_input is None for r in steps.records)
