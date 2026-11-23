"""F1 뒤·F3 앞 사건 채우기 단계 (이슈 #54 task-4). 진짜 모델·DB 없음."""

import json
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from patent_ai.core.agents import orchestrator
from patent_ai.core.agents.orchestrator import CaseInput, FilledTexts, run_case
from patent_ai.core.agents.step_inputs import InputMissing
from patent_ai.core.agents.steps import MemoryStepRecorder
from patent_ai.core.f3_claim_compare.inputs import F3Inputs
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.common import Status, StatusValue
from patent_ai.core.schemas.document import PageText

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "f1"
APP_VALUE, DISPATCH_VALUE = "1020990000001", "952099000000001"
OK = Status(value=StatusValue.CONFIRMED, checked="가짜")
TEXTS = F3Inputs(
    claims_at_oa={1: "가 장치."},
    claims_status=OK,
    claims_document_id="doc_spec",
    spec=PageText(document_id="doc_spec", pages=[], status=OK),
)


class Store:
    def find_oa(self, application_number, dispatch_number):
        return None

    def find_case(self, application_number):
        return None


class Filler:
    def __init__(self, out=None, boom=False):
        self.out, self.boom = out, boom
        self.calls: list[tuple] = []

    def fill(self, oa_id, application_number, dispatch_number):
        self.calls.append((oa_id, application_number, dispatch_number))
        if self.boom:
            raise RuntimeError("DB 끊김")
        return self.out


def _go(tmp_path, fill_case, *, with_numbers=True, texts=None, steps=None):
    pdf = tmp_path / "oa.pdf"
    c = canvas.Canvas(str(pdf))
    c.drawString(72, 720, "Application No. 10-2099-0000001" if with_numbers else "Notice")
    c.drawString(72, 700, "Dispatch No. 9-5-2099-000000001")
    c.showPage()
    c.save()
    cfg = tmp_path / "orchestrator.yaml"
    cfg.write_text("plan: fixed_order\nfixed_order: [extract_pages, read_oa, run_f3]\n", "utf-8")
    answer = json.loads((FIXTURES / "llm" / "basic.json").read_text("utf-8"))
    if not with_numbers:
        answer["application_number"] = None
    transport = FakeTransport(
        {"f1.read_oa": [TransportResponse(json.dumps(answer, ensure_ascii=False), 100, 50)]}
    )
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    case = CaseInput(case_id="c_1", oa_document=pdf, oa_document_id="d_1", texts=texts)
    steps = steps or MemoryStepRecorder()
    out = run_case(case, "oa_1", "r_1", Store(), cfg, ctx=ctx, steps=steps, fill_case=fill_case)
    return out, steps.records


@pytest.fixture
def seen_texts(monkeypatch):
    """F3 입력에 들어간 글자를 잡고 F3는 넘긴다 (F3 모델 응답 없이 잇기만 본다)."""
    seen: list = []

    def fake_f3_input(results, case_id, texts):
        seen.append(texts)
        return InputMissing("input_unverified: 테스트에서 F3는 안 돌림")

    monkeypatch.setattr(orchestrator, "f3_input", fake_f3_input)
    return seen


def test_번호를_읽은_뒤_자르기_앞에서_채우고_그_글자로_F3를_부른다(tmp_path, seen_texts):
    filler = Filler(FilledTexts(texts=TEXTS, reason="local_folder로 채움"))
    out, records = _go(tmp_path, filler)
    assert filler.calls == [("oa_1", APP_VALUE, DISPATCH_VALUE)]
    names = [r.tool_name for r in records]
    assert names.index("read_oa") < names.index("fill_case") < names.index("cut_to_oa")
    step = next(r for r in records if r.tool_name == "fill_case")
    assert (step.step_kind, step.outcome, step.reason) == (
        "fixed_stage",
        "ok",
        "local_folder로 채움",
    )
    assert seen_texts == [TEXTS]


def test_글자를_못_만들면_F3_넘긴_이유에_채우기_이유가_붙는다(tmp_path):
    filler = Filler(FilledTexts(texts=None, reason="출원서 없음 (lookup_failed)"))
    out, records = _go(tmp_path, filler)
    assert out.state == "succeeded"
    assert "사건 채우기: 출원서 없음 (lookup_failed)" in out.skipped["run_f3"]
    step = next(r for r in records if r.tool_name == "fill_case")
    assert step.result_status == "unverified"


def test_채우기가_글자를_못_만들면_부르는_쪽이_준_글자를_그대로_쓴다(tmp_path, seen_texts):
    _go(tmp_path, Filler(FilledTexts(texts=None, reason="없음")), texts=TEXTS)
    assert seen_texts == [TEXTS]


def test_채우기가_없으면_지금처럼_돈다(tmp_path):
    out, records = _go(tmp_path, None)
    assert "fill_case" not in [r.tool_name for r in records]
    assert "사건 채우기" not in out.skipped["run_f3"]


def test_번호를_모르면_채우지_않는다(tmp_path):
    filler = Filler(FilledTexts(texts=TEXTS, reason="x"))
    out, _ = _go(tmp_path, filler, with_numbers=False)
    assert out.state == "waiting_for_human" and filler.calls == []


def test_채우기_예외는_실패_기록을_남기고_올린다(tmp_path):
    steps = MemoryStepRecorder()
    with pytest.raises(RuntimeError):
        _go(tmp_path, Filler(boom=True), steps=steps)
    last = steps.records[-1]
    assert (last.tool_name, last.outcome) == ("fill_case", "failed")
