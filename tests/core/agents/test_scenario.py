"""사건 1건 시나리오와 단계 기록 테스트 (tasks-2.md m1-i2-15 task-4). 진짜 모델 호출 없음.

통지서 글자: reportlab 기본 글꼴은 한글을 못 그려서, extract_pages 자리에 지어낸 통지서 글자
fixture(tests/fixtures/f1/notice_basic.pages.json)를 끼운다. 그 뒤(read_oa 규칙+모델 합치기,
지휘 그래프)는 진짜 코드로 돈다. 모델 답은 가짜 전송층(basic.json).
"""

import json
from pathlib import Path

import pytest

from patent_ai.core.agents.orchestrator import CaseInput, run_case
from patent_ai.core.agents.steps import MemoryStepRecorder, StepRecord
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


def _go(
    tmp_path,
    plan="fixed_order",
    responses=None,
    order="extract_pages, read_oa",
    max_steps=10,
    recorder=None,
    run_id="r_1",
):
    cfg = tmp_path / "o.yaml"
    cfg.write_text(
        f"plan: {plan}\nfixed_order: [{order}]\nmax_steps: {max_steps}\n", encoding="utf-8"
    )
    ctx = RunContext(
        run_id="r_1",
        budget=CallBudget(),
        recorder=recorder or MemoryRecorder(),
        transport=FakeTransport(responses if responses is not None else {"f1.read_oa": [_basic()]}),
    )
    case = CaseInput(
        case_id="c_1", oa_document=tmp_path / "oa.pdf", oa_document_id="d_1", materials=["자료"]
    )
    steps = MemoryStepRecorder()
    out = run_case(case, "oa_1", run_id, _Store(), cfg, ctx=ctx, steps=steps)
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
        ("code_tool", "prepare_units"),  # 글자가 없어 넘긴 줄 (skip 기록은 code_tool로 적음)
    ]
    assert [r.reason for r in steps.records][:3] == ["고정 단계", "고정 순서", "고정 단계"]
    assert all(isinstance(r, StepRecord) and r.run_id == "r_1" for r in steps.records)
    assert [r.outcome for r in steps.records] == ["ok", "ok", "ok", "skipped"]
    # read_oa 안에서 모델을 한 번 불렀다
    assert [r.model_call_count for r in steps.records] == [0, 1, 0, None]


def test_잘린_답으로_다시_부른_호출도_모델_호출_수에_센다(tmp_path, notice_pages):
    # 첫 답이 max_tokens에 닿아 잘림(output_truncated) -> read_oa가 한 번 더 부름 (#172)
    cut = TransportResponse('{"application_number": ', 100, 50, "max_tokens")
    out, steps = _go(tmp_path, responses={"f1.read_oa": [cut, _basic()]})
    assert out.state == "succeeded"
    assert [r.model_call_count for r in steps.records] == [0, 2, 0, None]


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


def test_빠진_자료는_fixture_사건으로_보류_목록을_잰다_run_결과로는_54에서(tmp_path, notice_pages):
    out, _ = _go(tmp_path)
    assert out.state == "succeeded"
    # (#54에서 cut_to_oa가 자료를 묶으면 run 결과로 다시 잰다)
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


def test_run_case_OAResult는_read_oa를_직접_돌린_것과_같다(tmp_path, notice_pages):
    from patent_ai.core.f1_oa_reader.read_oa import read_oa

    out, _ = _go(tmp_path)
    ctx = RunContext(
        run_id="r_1",
        budget=CallBudget(),
        recorder=MemoryRecorder(),
        transport=FakeTransport({"f1.read_oa": [_basic()]}),
    )
    expected = read_oa(notice_pages, "d_1", "oa_1", "r_1", ctx=ctx)
    assert out.results["read_oa"].model_dump() == expected.model_dump()


def test_run_id가_ctx와_다르면_ValueError(tmp_path, notice_pages):
    with pytest.raises(ValueError, match="run_id"):
        _go(tmp_path, run_id="r_other")


def _last(steps):
    return steps.records[-1]


def test_agent_잘못된_도구_선택은_decide_failed(tmp_path, notice_pages):
    out, steps = _go(tmp_path, plan="agent", responses={"agents.orchestrator": [_decision("없음")]})
    assert out.error["code"] == "invalid_tool_choice"
    assert (_last(steps).step_kind, _last(steps).outcome) == ("decide", "failed")


def test_agent_read_oa_없이_stop이면_decide_failed(tmp_path, notice_pages):
    out, steps = _go(tmp_path, plan="agent", responses={"agents.orchestrator": [_decision("stop")]})
    assert out.error["code"] == "no_oa_result"
    assert (_last(steps).step_kind, _last(steps).outcome) == ("decide", "failed")


def test_agent_max_steps는_decide_failed(tmp_path, notice_pages):
    resp = {"agents.orchestrator": [_decision("extract_pages")] * 5}
    out, steps = _go(tmp_path, plan="agent", responses=resp, max_steps=2)
    assert out.error["code"] == "max_steps"
    assert (_last(steps).step_kind, _last(steps).outcome) == ("decide", "failed")


def test_fixed_order에서도_잘못된_이름은_decide_failed_한_줄(tmp_path, notice_pages):
    out, steps = _go(tmp_path, order="extract_pages, 없음")
    assert out.error["code"] == "invalid_tool_choice"
    decides = [r for r in steps.records if r.step_kind == "decide"]
    assert [(r.tool_name, r.outcome, r.reason) for r in decides] == [
        ("없음", "failed", "고정 순서")
    ]


def test_fixed_order_max_steps는_decide_failed(tmp_path, notice_pages):
    out, steps = _go(tmp_path, max_steps=1)
    assert out.error["code"] == "max_steps"
    assert (_last(steps).step_kind, _last(steps).outcome) == ("decide", "failed")


def test_셀_수_없는_기록기면_모델_호출_수는_None(tmp_path, notice_pages):
    class Opaque:
        def record(self, rec):
            pass

    _, steps = _go(tmp_path, recorder=Opaque())
    assert [r.model_call_count for r in steps.records] == [None, None, None, None]


def test_StepRecord는_result_id_칸이_있고_기본은_None(tmp_path, notice_pages):
    _, steps = _go(tmp_path)
    assert all(r.result_id is None for r in steps.records)


def test_core가_서버용_타입을_내보낸다():
    from patent_ai import core

    for name in (
        "run_case",
        "CaseInput",
        "RunOutcome",
        "CaseStore",
        "StepRecorder",
        "MemoryStepRecorder",
        "WaitingFor",
    ):
        assert hasattr(core, name)
