"""고정 순서(plan=fixed_order) 테스트 (이슈 #166 T1). 진짜 모델 호출 없음.

기대값은 이슈 #166 본문 T1: 순서는 설정에서 읽고(F1 → F3 → F2 → F4), 도구가 아직 없는 단계는
"확인되지 않음"으로 넘기되 경고와 이유를 남긴다. 넘겨도 된다는 표시가 없는 이름은 설정 오류다.
"""

import json
import logging
from pathlib import Path

import pytest
import yaml

from patent_ai.core.agents.orchestrator import CaseInput, run_case
from patent_ai.core.agents.steps import MemoryStepRecorder
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.document import PageText

ROOT = Path(__file__).resolve().parents[3]
F1 = ROOT / "tests" / "fixtures" / "f1"
REAL_CONFIG = ROOT / "config" / "orchestrator.yaml"
F1_STEPS = ["extract_pages", "read_oa"]


class _Store:
    def find_oa(self, application_number, dispatch_number):
        return None

    def find_case(self, application_number):
        return None


def _basic() -> TransportResponse:
    return TransportResponse((F1 / "llm" / "basic.json").read_text("utf-8"), 100, 50)


def _decision(name: str) -> TransportResponse:
    return TransportResponse(json.dumps({"next_tool": name, "reason": f"{name} 차례"}), 10, 10)


@pytest.fixture
def notice_pages(monkeypatch):
    """지어낸 통지서 글자를 extract_pages 자리에 끼운다 (PDF를 만들지 않는다)."""
    pages = PageText.model_validate_json((F1 / "notice_basic.pages.json").read_text("utf-8"))
    monkeypatch.setattr("patent_ai.core.f1_oa_reader.pages.extract_pages", lambda p, d: pages)
    return pages


def _write(tmp_path, body: dict) -> Path:
    cfg = tmp_path / "o.yaml"
    cfg.write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")
    return cfg


def _go(tmp_path, body: dict, responses=None):
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
    out = run_case(case, "oa_1", "r_1", _Store(), _write(tmp_path, body), ctx=ctx, steps=steps)
    return out, steps


def test_저장소_설정의_순서는_F1_F3_F2_F4이고_plan_기본값은_agent():
    cfg = yaml.safe_load(REAL_CONFIG.read_text("utf-8"))
    assert cfg["plan"] == "agent"
    assert cfg["fixed_order"] == ["extract_pages", "read_oa", "run_f3", "run_f2", "run_f4"]
    # F2 도구는 아직 없다: 넘겨도 되는 단계로 적혀 있어야 한다
    assert "run_f2" in cfg["skip_if_missing"]
    # F1 단계는 넘길 수 없다
    assert not set(cfg["skip_if_missing"]) & set(F1_STEPS)


def test_도구가_없는_단계는_확인되지_않음으로_넘기고_이유와_경고를_남긴다(
    tmp_path, notice_pages, caplog
):
    body = {
        "plan": "fixed_order",
        "fixed_order": [*F1_STEPS, "run_f2"],
        "skip_if_missing": ["run_f2"],
    }
    with caplog.at_level(logging.WARNING):
        out, steps = _go(tmp_path, body)
    # 나머지 단계는 끝까지 돈다
    assert out.state == "succeeded"
    assert out.trace == ["extract_pages", "read_oa", "cut_to_oa"]
    # 넘긴 단계는 결과에도, 돈 순서에도 없다 (성공한 것처럼 보이지 않는다)
    assert "run_f2" not in out.results
    assert list(out.skipped) == ["run_f2"]
    assert "tool_missing" in out.skipped["run_f2"]
    # 단계 기록 한 줄: ok가 아니고, 확인되지 않음이며, 넘긴 이유가 있다
    rec = steps.records[-1]
    assert rec.tool_name == "run_f2"
    assert rec.outcome != "ok"
    assert rec.reason == "넘김: " + out.skipped["run_f2"]  # DB에 남는 칸(reason)에 이유가 있다
    assert rec.result_status == "unverified"
    assert rec.skipped_reason == out.skipped["run_f2"]
    # 넘기지 않은 단계에는 이유 칸이 비어 있다
    assert all(r.skipped_reason is None for r in steps.records[:-1])
    assert any("run_f2" in r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING)


def test_넘긴_단계가_가운데에_있어도_뒤_단계는_돈다(tmp_path, notice_pages):
    body = {
        "plan": "fixed_order",
        "fixed_order": ["extract_pages", "run_f2", "read_oa"],
        "skip_if_missing": ["run_f2"],
    }
    out, steps = _go(tmp_path, body)
    assert out.state == "succeeded"
    assert [r.tool_name for r in steps.records] == [
        "extract_pages",
        "run_f2",
        "read_oa",
        "cut_to_oa",
    ]
    assert len([r for r in steps.records if r.tool_name == "run_f2"]) == 1  # 한 번만 적는다


def test_표시_없는_모르는_단계_이름은_설정_오류로_failed(tmp_path, notice_pages):
    body = {"plan": "fixed_order", "fixed_order": [*F1_STEPS, "run_f2"]}
    out, steps = _go(tmp_path, body)
    assert out.state == "failed"
    assert out.error["code"] == "invalid_tool_choice"
    assert "run_f2" in out.error["message"] and "skip_if_missing" in out.error["message"]
    assert out.skipped == {}
    assert (steps.records[-1].step_kind, steps.records[-1].outcome) == ("decide", "failed")


def test_넘겨도_된다고_적혀도_도구가_있으면_그대로_돈다(tmp_path, notice_pages):
    body = {"plan": "fixed_order", "fixed_order": F1_STEPS, "skip_if_missing": ["read_oa"]}
    out, _ = _go(tmp_path, body)
    assert out.state == "succeeded"
    assert out.skipped == {} and "read_oa" in out.results


def test_agent_모드는_넘김_표시와_상관없이_없는_도구를_고르면_failed(tmp_path, notice_pages):
    body = {"plan": "agent", "fixed_order": F1_STEPS, "skip_if_missing": ["run_f2"]}
    out, _ = _go(tmp_path, body, {"agents.orchestrator": [_decision("run_f2")]})
    assert out.state == "failed"
    assert out.error["code"] == "invalid_tool_choice"
    assert out.skipped == {}


@pytest.mark.parametrize(
    "body",
    [
        {"plan": "fixed_order", "fixed_order": "extract_pages"},
        {"plan": "fixed_order", "fixed_order": ["extract_pages", 3]},
        {"plan": "fixed_order", "fixed_order": F1_STEPS, "skip_if_missing": "run_f2"},
    ],
)
def test_순서나_넘김_목록이_이름_목록이_아니면_ValueError(tmp_path, notice_pages, body):
    with pytest.raises(ValueError, match="fixed_order|skip_if_missing"):
        _go(tmp_path, body)
