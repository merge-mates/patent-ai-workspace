"""멈추는 조건과 사람 기다림 테스트 (tasks-2.md m1-i2-15 task-3). 진짜 모델 호출 없음."""

import json
from pathlib import Path

from reportlab.pdfgen import canvas

from patent_ai.core.agents.orchestrator import CaseInput, WaitingFor, run_case
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "f1"
APP = "10-2099-0000001"
DISPATCH = "9-5-2099-000000001"


class FakeStore:
    def __init__(self, oa=None, case=None):
        self.oa, self.case = oa, case
        self.calls: list[tuple] = []

    def find_oa(self, application_number, dispatch_number):
        self.calls.append(("find_oa", application_number, dispatch_number))
        return self.oa

    def find_case(self, application_number):
        self.calls.append(("find_case", application_number))
        return self.case


def _answer(drop_numbers: bool) -> TransportResponse:
    d = json.loads((FIXTURES / "llm" / "basic.json").read_text("utf-8"))
    if drop_numbers:
        d["application_number"] = None
    return TransportResponse(json.dumps(d, ensure_ascii=False), 100, 50)


def _go(tmp_path, *, with_numbers=True, store=None, plan="fixed_order", max_steps=10, extra=None):
    pdf = tmp_path / "oa.pdf"
    c = canvas.Canvas(str(pdf))
    # 번호가 있는 통지서 / 번호 글자가 하나도 없는 통지서
    c.drawString(72, 720, f"Application No. {APP}" if with_numbers else "Notice of reasons")
    c.drawString(72, 700, f"Dispatch No. {DISPATCH}" if with_numbers else "Please respond")
    c.showPage()
    c.save()
    cfg = tmp_path / "orchestrator.yaml"
    cfg.write_text(
        f"plan: {plan}\nfixed_order: [extract_pages, read_oa]\nmax_steps: {max_steps}\n",
        encoding="utf-8",
    )
    transport = FakeTransport({"f1.read_oa": [_answer(not with_numbers)]})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    case = CaseInput(case_id="c_new", oa_document=pdf, oa_document_id="d_1", materials=["자료"])
    return run_case(case, "oa_1", "r_1", store, cfg, ctx=ctx)


def test_출원번호_없는_통지서는_사람을_기다리며_멈춘다(tmp_path):
    store = FakeStore()
    out = _go(tmp_path, with_numbers=False, store=store)
    assert out.state == "waiting_for_human"
    assert out.waiting_for == WaitingFor.APPLICATION_NUMBER
    assert out.error is None
    assert "read_oa" in out.results  # F1 결과는 그대로 돌려준다
    assert "cut_to_oa" not in out.results  # 출원번호를 모르니 자르기는 안 돈다
    assert out.case_id == "c_new"
    assert store.calls == []  # 번호를 모르면 사건을 찾아보지 않는다


def test_번호가_확인되고_저장소에_없으면_끝까지_돈다(tmp_path):
    store = FakeStore()
    out = _go(tmp_path, store=store)
    assert out.state == "succeeded"
    assert out.waiting_for is None
    assert out.case_id == "c_new"
    assert ("find_oa", APP, DISPATCH) in store.calls


def test_같은_OA가_이미_있으면_failed와_기존_ID(tmp_path):
    out = _go(tmp_path, store=FakeStore(oa=("c_old", "oa_old")))
    assert out.state == "failed"
    assert out.error == {
        "code": "oa_already_exists",
        "message": out.error["message"],
        "case_id": "c_old",
        "oa_id": "oa_old",
    }
    assert out.case_id == "c_old"
    assert "cut_to_oa" not in out.results


def test_기존_사건의_다음_OA면_최종_case_id가_기존_사건(tmp_path):
    out = _go(tmp_path, store=FakeStore(oa=None, case="c_old"))
    assert out.state == "succeeded"
    assert out.case_id == "c_old"


def test_max_steps에_닿으면_failed와_찾아본_범위(tmp_path):
    out = _go(tmp_path, max_steps=2)
    assert out.state == "failed"
    assert out.error["code"] == "max_steps"
    assert "extract_pages" in out.searched_scope and "read_oa" in out.searched_scope
    assert "extract_pages" in out.error["message"]
    assert "cut_to_oa" not in out.results
