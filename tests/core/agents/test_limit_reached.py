"""묶음 밖 호출 상한(이슈 #241, ADR 0003): F1 읽기·지휘 모델. 네트워크·키 없음.

F3·F2·F4 단계의 상한은 여기서 다루지 않는다 (F3 청구항 나누기는 #317·PR #322).
"""

import pytest

from patent_ai.core.agents import orchestrator
from patent_ai.core.agents.orchestrator import CaseInput, NextAction, limit_reason, run_case
from patent_ai.core.agents.steps import MemoryStepRecorder
from patent_ai.core.llm.errors import ModelCallLimitExceeded
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport
from tests.core.agents.test_orchestrator import READ_OA, _basic, _config, _EmptyStore, _pdf

SECRET = "비밀 원문 문장" * 20


def _over(*a, **k):
    e = ModelCallLimitExceeded("max_model_calls", 3, 2)
    e.args = (SECRET,)  # str(e)에 긴 원문이 섞여도 이유에는 없어야 한다
    raise e


def _run(tmp_path, plan):
    ctx = RunContext(
        run_id="r_1",
        budget=CallBudget(),
        recorder=MemoryRecorder(),
        transport=FakeTransport({READ_OA: [_basic()]}),
    )
    steps = MemoryStepRecorder()
    case = CaseInput(
        case_id="c_1", oa_document=_pdf(tmp_path), oa_document_id="d_1", materials=["자료1"]
    )
    out = run_case(
        case, "oa_1", "r_1", _EmptyStore(), _config(tmp_path, plan), ctx=ctx, steps=steps
    )
    return out, steps


def _no_leak(text: str) -> None:
    assert SECRET[:10] not in text
    assert "max_model_calls" in text and "2" in text


def test_F1_읽기_상한이면_failed_limit_reached와_단계_줄(tmp_path, monkeypatch):
    monkeypatch.setattr("patent_ai.core.f1_oa_reader.read_oa.read_oa", _over)
    out, steps = _run(tmp_path, "fixed_order")
    assert out.state == "failed" and out.error["code"] == "limit_reached"
    assert out.error["message"] == limit_reason(
        "read_oa", ModelCallLimitExceeded("max_model_calls", 3, 2)
    )
    _no_leak(out.error["message"])
    (rec,) = [r for r in steps.records if r.outcome == "limit_reached"]
    assert rec.tool_name == "read_oa" and rec.skipped_reason == out.error["message"]
    assert "cut_to_oa" not in out.results


def test_지휘_모델이_read_oa_전에_상한이면_failed_limit_reached(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrator, "_ask_model", _over)
    out, steps = _run(tmp_path, "agent")
    assert out.state == "failed" and out.error["code"] == "limit_reached"
    _no_leak(out.error["message"])
    assert [(r.step_kind, r.outcome) for r in steps.records if r.step_kind == "decide"] == [
        ("decide", "limit_reached")
    ]


def test_지휘_모델이_read_oa_뒤에_상한이면_succeeded와_넘긴_이유(tmp_path, monkeypatch):
    calls = []

    def ask(registry, state, ctx):
        calls.append(1)
        if len(calls) == 1:
            return NextAction(next_tool="read_oa", reason="테스트")
        return _over()

    monkeypatch.setattr(orchestrator, "_ask_model", ask)
    out, steps = _run(tmp_path, "agent")
    assert out.state == "succeeded" and out.error is None
    assert "read_oa" in out.results and "cut_to_oa" in out.results
    # 아직 결과도 넘김도 없는 F3·F2·F4가 같은 이유로 넘어간다 (decide는 넘긴 목록에 없다)
    assert list(out.skipped) == ["run_f3", "run_f2", "run_f4"]
    for why in out.skipped.values():
        assert why == limit_reason("decide", ModelCallLimitExceeded("max_model_calls", 3, 2))
        _no_leak(why)
    limited = [(r.step_kind, r.tool_name) for r in steps.records if r.outcome == "limit_reached"]
    assert limited == [
        ("decide", "decide"),
        ("code_tool", "run_f3"),
        ("code_tool", "run_f2"),
        ("code_tool", "run_f4"),
    ]
    # 넘긴 줄만 skipped_reason을 가진다 (decide 줄은 목록에 안 나온다)
    assert [r.tool_name for r in steps.records if r.skipped_reason] == [
        "run_f3",
        "run_f2",
        "run_f4",
    ]


@pytest.mark.parametrize("plan", ["fixed_order"])
def test_상한이_아니면_limit_reached_줄이_없다(tmp_path, plan):
    out, steps = _run(tmp_path, plan)
    assert out.state == "succeeded"
    assert not [r for r in steps.records if r.outcome == "limit_reached"]


def test_read_oa가_아닌_도구가_상한이면_기존대로_failed(tmp_path, monkeypatch):
    # ADR 0003·API 문서의 "그 밖 단계가 상한을 올리면 기존대로 failed" 가지 (#331 리뷰)
    monkeypatch.setattr("patent_ai.core.f1_oa_reader.pages.extract_pages", _over)
    out, steps = _run(tmp_path, "fixed_order")
    assert out.state == "failed" and out.error["code"] == "ModelCallLimitExceeded"
    assert [r.tool_name for r in steps.records if r.outcome == "failed"] == ["extract_pages"]
    assert not [r for r in steps.records if r.outcome == "limit_reached"]
