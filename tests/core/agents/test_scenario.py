"""사건 1건 시나리오와 단계 기록 테스트 (tasks-2.md m1-i2-15 task-4). 진짜 모델 호출 없음.

통지서 글자: reportlab 기본 글꼴은 한글을 못 그려서, extract_pages 자리에 지어낸 통지서 글자
fixture(tests/fixtures/f1/notice_basic.pages.json)를 끼운다. 그 뒤(read_oa 규칙+모델 합치기,
지휘 그래프)는 진짜 코드로 돈다. 모델 답은 가짜 전송층(basic.json).
"""

import json
from pathlib import Path

import pytest
from patent_ai.core.agents.steps import MemoryStepRecorder, StepRecord

from patent_ai.core.agents.orchestrator import CaseInput, run_case
from patent_ai.core.f1_oa_reader.pages import PdfReadError
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.case_materials import CaseMaterials
from patent_ai.core.schemas.document import PageText
from patent_ai.core.schemas.oa_result import OAResult
from patent_ai.core.schemas.propagation import collect_review_items

TESTS = Path(__file__).resolve().parents[2]
F1 = TESTS / "fixtures" / "f1"
CASE = TESTS / "fixtures" / "case_missing_citation"


class _Store:
    def find_oa(self, application_number, dispatch_number):
        return None

    def find_case(self, application_number):
        return None


def _decision(name: str) -> TransportResponse:
    return TransportResponse(json.dumps({"next_tool": name, "reason": f"{name} 차례"}), 10, 10)


def _basic() -> TransportResponse:
    return TransportResponse((F1 / "llm" / "basic.json").read_text("utf-8"), 100, 50)


@pytest.fixture
def notice_pages(monkeypatch):
    pages = PageText.model_validate_json((F1 / "notice_basic.pages.json").read_text("utf-8"))
    monkeypatch.setattr("patent_ai.core.f1_oa_reader.pages.extract_pages", lambda p, d: pages)
    return pages


def _go(tmp_path, plan="fixed_order", responses=None):
    cfg = tmp_path / "o.yaml"
    cfg.write_text(
        f"plan: {plan}\nfixed_order: [extract_pages, read_oa]\nmax_steps: 10\n", encoding="utf-8"
    )
    ctx = RunContext(
        run_id="r_1",
        budget=CallBudget(),
        recorder=MemoryRecorder(),
        transport=FakeTransport(responses if responses is not None else {"f1.read_oa": [_basic()]}),
    )
    case = CaseInput(
        case_id="c_1", oa_document=tmp_path / "oa.pdf", oa_document_id="d_1", materials=["자료"]
    )
    steps = MemoryStepRecorder()
    out = run_case(case, "oa_1", "r_1", _Store(), cfg, ctx=ctx, steps=steps)
    return out, steps


def test_사건_1건을_끝까지_돌고_도구마다_기록_한_줄(tmp_path, notice_pages):
    out, steps = _go(tmp_path)
    assert out.state == "succeeded"
    assert isinstance(out.results["read_oa"], OAResult)
    assert out.trace == ["extract_pages", "read_oa", "cut_to_oa"]
    assert [(r.step_kind, r.tool_name) for r in steps.records] == [
        ("code_tool", "extract_pages"),
        ("code_tool", "read_oa"),
        ("fixed_stage", "cut_to_oa"),
    ]
    assert [r.reason for r in steps.records] == ["고정 단계", "고정 순서", "고정 단계"]
    assert all(isinstance(r, StepRecord) and r.run_id == "r_1" for r in steps.records)
    assert all(r.outcome == "ok" for r in steps.records)
    # read_oa 안에서 모델을 한 번 불렀다
    assert [r.model_call_count for r in steps.records] == [0, 1, 0]
    assert steps.records[1].result_status == "unverified" or steps.records[1].result_status


def test_agent_모드는_지휘_판단_이유를_기록한다(tmp_path, notice_pages):
    responses = {
        "agents.orchestrator": [_decision("read_oa"), _decision("stop")],
        "f1.read_oa": [_basic()],
    }
    out, steps = _go(tmp_path, plan="agent", responses=responses)
    assert out.state == "succeeded"
    kinds = [(r.step_kind, r.tool_name, r.reason) for r in steps.records]
    assert ("decide", "read_oa", "read_oa 차례") in kinds
    assert ("decide", "stop", "stop 차례") in kinds
    assert ("code_tool", "read_oa", "지휘 선택") in kinds
    assert all(r.model_call_count == 1 for r in steps.records if r.step_kind == "decide")


def test_인용문헌_하나_없으면_보류_목록에_뜨고_실행은_성공이다(tmp_path, notice_pages):
    out, _ = _go(tmp_path)
    assert out.state == "succeeded"
    # cut_to_oa 몸통이 #54 전까지 가짜라 빠진 자료는 #14 fixture 사건으로 확인한다
    oa = OAResult.model_validate_json((CASE / "oa_result.json").read_text("utf-8"))
    materials = CaseMaterials.model_validate_json((CASE / "case_materials.json").read_text("utf-8"))
    items = collect_review_items([oa], materials)
    assert [i.kind for i in items].count("missing_material") == 1


def test_실패한_도구도_기록_한_줄(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise PdfReadError("PDF를 읽지 못함")

    monkeypatch.setattr("patent_ai.core.f1_oa_reader.pages.extract_pages", boom)
    out, steps = _go(tmp_path)
    assert out.state == "failed"
    assert [(r.tool_name, r.outcome) for r in steps.records] == [("extract_pages", "failed")]
    assert steps.records[0].result_status is None


def test_steps_없이_부르면_ValueError(tmp_path):
    cfg = tmp_path / "o.yaml"
    cfg.write_text("plan: fixed_order\n", encoding="utf-8")
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=FakeTransport({})
    )
    case = CaseInput(case_id="c", oa_document=tmp_path / "x.pdf", oa_document_id="d")
    with pytest.raises(ValueError, match="steps"):
        run_case(case, "oa_1", "r_1", _Store(), cfg, ctx=ctx, steps=None)


def test_번호를_몰라_멈춘_것도_기록한다(tmp_path, monkeypatch):
    pages = PageText.model_validate_json((F1 / "notice_basic.pages.json").read_text("utf-8"))
    monkeypatch.setattr("patent_ai.core.f1_oa_reader.pages.extract_pages", lambda p, d: pages)
    answer = json.loads((F1 / "llm" / "basic.json").read_text("utf-8"))
    answer["application_number"] = None
    # 규칙이 읽은 번호는 지우고 글자 속 번호를 바꿔 출원번호를 못 읽게 한다
    gone = pages.model_copy(
        update={
            "pages": [
                p.model_copy(update={"text": p.text.replace("출원번호 10-2099-0000001", "")})
                for p in pages.pages
            ]
        }
    )
    monkeypatch.setattr("patent_ai.core.f1_oa_reader.pages.extract_pages", lambda p, d: gone)
    resp = {"f1.read_oa": [TransportResponse(json.dumps(answer), 10, 10)]}
    out, steps = _go(tmp_path, responses=resp)
    assert out.state == "waiting_for_human"
    assert steps.records[-1].outcome == "waiting"
