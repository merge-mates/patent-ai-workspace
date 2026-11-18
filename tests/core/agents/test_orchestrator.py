"""지휘 그래프 뼈대 테스트 (tasks-2.md m1-i2-15 task-2). 진짜 모델 호출 없음.

PDF는 지어낸 글자로 만들고, 모델 답은 가짜 전송층(FakeTransport)이 준다.
"""

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError
from reportlab.pdfgen import canvas

from patent_ai import core
from patent_ai.core.agents.orchestrator import CaseInput, run_case
from patent_ai.core.agents.steps import MemoryStepRecorder
from patent_ai.core.agents.tools import ToolOutputInvalid
from patent_ai.core.f1_oa_reader.pages import PdfReadError
from patent_ai.core.llm.errors import ModelCallFailed, ModelCallLimitExceeded, ModelOutputInvalid
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.oa_result import OAResult

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "f1"
ORCH = "agents.orchestrator"
READ_OA = "f1.read_oa"


def _text(answer) -> TransportResponse:
    return TransportResponse(json.dumps(answer, ensure_ascii=False), 100, 50)


def _decision(next_tool: str) -> TransportResponse:
    return _text({"next_tool": next_tool, "reason": "테스트"})


def _basic() -> TransportResponse:
    return _text(json.loads((FIXTURES / "llm" / "basic.json").read_text("utf-8")))


def _config(tmp_path: Path, plan: str, max_steps: int = 10) -> Path:
    p = tmp_path / "orchestrator.yaml"
    p.write_text(
        f"plan: {plan}\nfixed_order: [extract_pages, read_oa]\nmax_steps: {max_steps}\n",
        encoding="utf-8",
    )
    return p


def _pdf(tmp_path: Path) -> Path:
    path = tmp_path / "oa.pdf"
    c = canvas.Canvas(str(path))
    c.drawString(72, 720, "Application No. 10-2099-0000001")
    c.drawString(72, 700, "Dispatch No. 9-5-2099-000000001")
    c.showPage()
    c.save()
    return path


class _EmptyStore:
    def find_oa(self, application_number, dispatch_number):
        return None

    def find_case(self, application_number):
        return None


def _go(tmp_path, plan, responses, max_steps=10):
    transport = FakeTransport(responses)
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    case = CaseInput(
        case_id="c_1",
        oa_document=_pdf(tmp_path),
        oa_document_id="d_1",
        materials=["자료1"],
    )
    outcome = run_case(
        case,
        "oa_1",
        "r_1",
        _EmptyStore(),
        _config(tmp_path, plan, max_steps),
        ctx=ctx,
        steps=MemoryStepRecorder(),
    )
    return outcome, transport


def test_run_case는_core에서_내보낸다():
    assert core.run_case is run_case


def test_fixed_order는_세_도구를_차례로_돈다(tmp_path):
    outcome, transport = _go(tmp_path, "fixed_order", {READ_OA: [_basic()]})
    assert outcome.state == "succeeded"
    assert outcome.error is None
    assert outcome.case_id == "c_1"
    assert list(outcome.results) == ["extract_pages", "read_oa", "cut_to_oa"]
    assert isinstance(outcome.results["read_oa"], OAResult)
    assert outcome.results["cut_to_oa"].materials == ["자료1"]
    # 고정 순서에서는 지휘 모델을 부르지 않는다
    assert all(c["step"] != ORCH for c in transport.calls)


def test_agent_모드에서_지휘가_read_oa_뒤_stop을_골라도_자르기가_돈다(tmp_path):
    outcome, _ = _go(
        tmp_path,
        "agent",
        {ORCH: [_decision("read_oa"), _decision("stop")], READ_OA: [_basic()]},
    )
    assert outcome.state == "succeeded"
    assert "cut_to_oa" in outcome.results


@pytest.mark.parametrize("choice", ["cut_to_oa", "없는_도구"])
def test_지휘가_fixed_stage나_없는_도구를_고르면_failed(tmp_path, choice):
    outcome, _ = _go(tmp_path, "agent", {ORCH: [_decision(choice)]})
    assert outcome.state == "failed"
    assert outcome.error["code"] == "invalid_tool_choice"
    assert choice in outcome.error["message"]


def test_read_oa_없이_stop하면_failed(tmp_path):
    outcome, _ = _go(tmp_path, "agent", {ORCH: [_decision("stop")]})
    assert outcome.state == "failed"
    assert "cut_to_oa" not in outcome.results


class _Bad(BaseModel):
    n: int


def _raise_validation(*a, **k):
    _Bad.model_validate({"n": "가"})


@pytest.mark.parametrize(
    "exc",
    [
        ModelCallFailed("전송 실패"),
        ModelCallLimitExceeded("max_model_calls", 2, 2),
        ModelOutputInvalid("JSON 아님"),
        PdfReadError("PDF를 읽지 못함"),
        ToolOutputInvalid("출력이 이상함"),
    ],
)
@pytest.mark.parametrize("where", ["extract", "read"])
def test_도구_예외는_failed와_이유로(tmp_path, monkeypatch, exc, where):
    def boom(*a, **k):
        raise exc

    target = (
        "patent_ai.core.f1_oa_reader.pages.extract_pages"
        if where == "extract"
        else "patent_ai.core.f1_oa_reader.read_oa.read_oa"
    )
    monkeypatch.setattr(target, boom)
    outcome, _ = _go(tmp_path, "fixed_order", {READ_OA: [_basic()]})
    assert outcome.state == "failed"
    assert outcome.error["code"] == type(exc).__name__
    assert str(exc) in outcome.error["message"]
    assert "cut_to_oa" not in outcome.results


def test_입력_검사_오류도_failed(tmp_path, monkeypatch):
    monkeypatch.setattr("patent_ai.core.f1_oa_reader.pages.extract_pages", _raise_validation)
    outcome, _ = _go(tmp_path, "fixed_order", {READ_OA: [_basic()]})
    assert outcome.state == "failed"
    assert outcome.error["code"] == ValidationError.__name__
