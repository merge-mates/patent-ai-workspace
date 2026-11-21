"""고정 순서 한 바퀴 F1 → F3 → F2(없음) → F4 테스트 (이슈 #166 T2). 네트워크·키·DB 없음.

- 모델 답은 가짜 응답(FakeTransport), F3 검색은 메모리 저장소 + 가짜 임베딩(f3/scenario.py).
- F1 결과는 F4 fixture 사건(fixtures/f4/case_basic.json)의 OA 정리 결과를 read_oa 자리에 끼운다.
  명확성 검토까지 돌도록 청구항 2 줄에 OA가 짚은 문구('적당한 간격')만 더했다
  (F1 자체는 test_scenario.py가 진짜 코드로 본다. 여기서는 단계 사이 잇기를 본다).
"""

import json
import logging
from datetime import date
from pathlib import Path

import pytest
import yaml

from patent_ai.core.agents.orchestrator import CaseInput, run_case
from patent_ai.core.agents.steps import MemoryStepRecorder
from patent_ai.core.f3_claim_compare import run as f3_run
from patent_ai.core.f3_claim_compare.inputs import F3Inputs
from patent_ai.core.f3_claim_compare.result import F3Result
from patent_ai.core.f4_response_draft import run as f4_run
from patent_ai.core.f4_response_draft.result import F4Output
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.comparison import ClarityReview, ComparisonTable
from patent_ai.core.schemas.direction import DirectionCandidates
from patent_ai.core.schemas.document import PageText
from patent_ai.core.schemas.drafts import Drafts
from patent_ai.core.schemas.judgment_unit import JudgmentUnit
from patent_ai.core.schemas.oa_result import OAResult
from tests.core.f3 import scenario
from tests.core.f3.fakes import OK, bad, claim_row

ROOT = Path(__file__).resolve().parents[3]
F1 = ROOT / "tests" / "fixtures" / "f1"
F4 = ROOT / "tests" / "fixtures" / "f4"
REAL_CONFIG = ROOT / "config" / "orchestrator.yaml"
CASE = json.loads((F4 / "case_basic.json").read_text("utf-8"))
CHECKED_ON = date(2099, 2, 1)
TERM = "적당한 간격"  # OA가 짚은 명확성 문구
SENSOR, COVER, GAP = (
    "기판 위에 놓인 센서",
    "상기 센서를 덮는 투명 덮개",
    "상기 센서와 상기 덮개가 적당한 간격을 두고 떨어진",
)


class _Store:
    def find_oa(self, application_number, dispatch_number):
        return None

    def find_case(self, application_number):
        return None


def _text(body: dict) -> TransportResponse:
    return TransportResponse(json.dumps(body, ensure_ascii=False), 100, 50)


def _split(claim, elements, depends_on=(), quote=None):
    return _text(
        {
            "claim": claim,
            "depends_on": list(depends_on),
            "depends_on_quote": quote,
            "elements": [{"text": t} for t in elements],
        }
    )


def _row(no, judgment, *evidence):
    picks = [{"chunk_id": c, "quote": q} for c, q in evidence]
    return {"element_no": no, "citation": "D1", "judgment": judgment, "evidence": picks}


def _f4(*names) -> list[TransportResponse]:
    return [_text(json.loads((F4 / "llm" / f"{n}.json").read_text("utf-8"))) for n in names]


def _responses() -> dict:
    """단계마다 차례로 낼 가짜 응답 (F3 셋 + F4 셋)."""
    return {
        "f3.split_elements": [
            _split(1, [SENSOR, COVER]),
            _split(2, [GAP], [1], "제1항에 있어서"),
        ],
        "f3.compare": [
            _text(
                {
                    "claim": 1,
                    "rows": [
                        _row(1, "disclosed", (scenario.P23, "습도 센서는 흙에 꽂혀 습도를 잰다")),
                        _row(2, "difference_candidate"),
                    ],
                }
            ),
            _text({"claim": 2, "rows": [_row(1, "difference_candidate")]}),
        ],
        "f3.clarity": [
            _text(
                {
                    "claim": 2,
                    "terms": [
                        {
                            "term": TERM,
                            "issue_type": "optional_expression",
                            "note": "간격의 범위가 청구항에 적혀 있지 않음",
                            "definition": None,
                        }
                    ],
                }
            )
        ],
        "f4.direction": _f4("direction_inventive", "direction_clarity"),
        "f4.opinion": _f4("opinion_inventive", "opinion_clarity"),
        "f4.amendment": _f4("amendment_inventive", "amendment_clarity"),
    }


def _texts(claims_status=OK) -> F3Inputs:
    """실행 입력으로 주는 글자: OA 당시 청구항과 최초 명세서 (지어낸 것)."""
    return F3Inputs(
        claims_at_oa={c["claim"]: c["text"] for c in CASE["claims_text"]},
        claims_status=claims_status,
        claims_document_id="claims_1",
        spec=PageText.model_validate_json((F4 / "spec_basic.pages.json").read_text("utf-8")),
    )


@pytest.fixture
def wired(monkeypatch):
    """F1 두 단계와 F3 검색 자원을 지어낸 것으로 바꾼다 (진짜 DB·임베딩을 만들지 않는다)."""
    pages = PageText.model_validate_json((F1 / "notice_basic.pages.json").read_text("utf-8"))
    oa = OAResult.model_validate(
        {**CASE["oa"], "claim_rows": [claim_row(2, 2, clarity_terms=[TERM]).model_dump()]}
    )
    monkeypatch.setattr("patent_ai.core.f1_oa_reader.pages.extract_pages", lambda p, d: pages)
    monkeypatch.setattr("patent_ai.core.f1_oa_reader.read_oa.read_oa", lambda *a, **k: oa)
    monkeypatch.setattr(
        f3_run, "make_search_resources", lambda config, ctx: (scenario.searcher(), scenario.REPO)
    )
    return oa


def _real_config(tmp_path, plan="fixed_order") -> Path:
    """저장소 설정(config/orchestrator.yaml)의 순서·넘김 목록 그대로, plan만 바꾼 설정 파일."""
    body = yaml.safe_load(REAL_CONFIG.read_text("utf-8"))
    body["plan"] = plan
    cfg = tmp_path / "o.yaml"
    cfg.write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")
    return cfg


def _go(tmp_path, responses=None, plan="fixed_order", **case_fields):
    fields = {"texts": _texts(), "checked_on": CHECKED_ON, **case_fields}
    transport = FakeTransport(_responses() if responses is None else responses)
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    case = CaseInput(
        case_id="c_1",
        oa_document=tmp_path / "oa.pdf",
        oa_document_id="d_1",
        materials=["자료"],
        **fields,
    )
    steps = MemoryStepRecorder()
    out = run_case(
        case, "oa_1", "r_1", _Store(), _real_config(tmp_path, plan), ctx=ctx, steps=steps
    )
    return out, steps


def test_저장소_설정에서_넘겨도_되는_단계는_F2뿐이다():
    cfg = yaml.safe_load(REAL_CONFIG.read_text("utf-8"))
    assert cfg["skip_if_missing"] == ["run_f2"]


def test_고정_순서_한_바퀴가_돌고_F2를_넘긴_이유가_남는다(tmp_path, wired, caplog):
    with caplog.at_level(logging.WARNING):
        out, steps = _go(tmp_path)
    assert out.state == "succeeded" and out.error is None
    # F1 → (자르기) → F3 → F2 없음 → F4
    assert out.trace == ["extract_pages", "read_oa", "cut_to_oa", "run_f3", "run_f4"]
    assert [(r.tool_name, r.outcome) for r in steps.records] == [
        ("extract_pages", "ok"),
        ("read_oa", "ok"),
        ("cut_to_oa", "ok"),
        ("run_f3", "ok"),
        ("run_f2", "skipped"),
        ("run_f4", "ok"),
    ]
    # F2: 결과 없음 + 넘긴 이유 + 경고 (성공으로 보이지 않는다)
    assert "run_f2" not in out.results
    assert list(out.skipped) == ["run_f2"] and "tool_missing" in out.skipped["run_f2"]
    f2 = steps.records[4]
    assert f2.result_status == "unverified" and f2.skipped_reason == out.skipped["run_f2"]
    assert any("run_f2" in r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING)
    # 모델을 부른 단계는 F3·F4뿐
    assert [r.model_call_count for r in steps.records] == [0, 0, 0, 5, None, 6]


def test_단계_결과가_결과_스키마로_담긴다(tmp_path, wired):
    out, _ = _go(tmp_path)
    assert out.results["read_oa"] == wired
    f3, f4 = out.results["run_f3"], out.results["run_f4"]
    assert isinstance(f3, F3Result) and isinstance(f4, F4Output)
    assert f3.units and all(isinstance(u, JudgmentUnit) for u in f3.units)
    assert f3.comparisons and all(isinstance(t, ComparisonTable) for t in f3.comparisons)
    assert f3.clarity_reviews and all(isinstance(r, ClarityReview) for r in f3.clarity_reviews)
    assert f4.directions and all(isinstance(d, DirectionCandidates) for d in f4.directions)
    assert isinstance(f4.drafts, Drafts)
    assert f3.oa_id == f4.oa_id == "oa_1"


def test_F3_결과와_실행_입력_글자가_F4_입력으로_이어진다(tmp_path, wired, monkeypatch):
    seen = {}
    real = f4_run.run_f4

    def spy(inp, *, ctx):
        seen["inp"] = inp
        return real(inp, ctx=ctx)

    monkeypatch.setattr(f4_run, "run_f4", spy)
    out, _ = _go(tmp_path)
    inp, f3 = seen["inp"], out.results["run_f3"]
    assert inp.oa == wired
    assert (inp.units, inp.tables, inp.clarity) == (f3.units, f3.comparisons, f3.clarity_reviews)
    assert inp.held_tasks == f3.held_tasks  # 단위 안 보류를 F4가 후보에 표시하려고 받는다
    assert [u.unit_id for u in inp.units] == ["oa_1:29-2:c1", "oa_1:42-4-2:c2"]
    assert inp.legal == []  # F2가 없어 비어 있다 (F4가 확인되지 않음 묶음으로 채운다)
    assert [(c.claim, c.text, c.document_id) for c in inp.claims_text] == [
        (c["claim"], c["text"], "claims_1") for c in CASE["claims_text"]
    ]
    assert inp.spec == _texts().spec and inp.checked_on == CHECKED_ON


def test_F3_대비_출력_검사가_두_번_실패하면_failed로_끝나고_이유가_남는다(tmp_path, wired):
    responses = _responses()
    broken = TransportResponse("JSON 아님", 10, 10)
    responses["f3.compare"] = [broken, broken]
    out, steps = _go(tmp_path, responses)
    assert out.state == "failed"
    assert out.error["code"] == "ModelOutputInvalid" and out.error["message"]
    # 실패한 단계와 그 뒤 단계의 결과는 없다
    assert "run_f3" not in out.results and "run_f4" not in out.results
    assert out.trace == ["extract_pages", "read_oa", "cut_to_oa"]
    last = steps.records[-1]
    assert (last.tool_name, last.outcome, last.result_status) == ("run_f3", "failed", None)


def test_F4_단계가_실패해도_failed로_끝난다(tmp_path, wired):
    responses = _responses()
    broken = TransportResponse("JSON 아님", 10, 10)
    responses["f4.direction"] = [broken, broken]
    out, steps = _go(tmp_path, responses)
    assert out.state == "failed" and out.error["message"]
    assert isinstance(out.results["run_f3"], F3Result) and "run_f4" not in out.results
    assert (steps.records[-1].tool_name, steps.records[-1].outcome) == ("run_f4", "failed")


def test_청구항_글자_입력이_없으면_F3_F4를_input_unverified로_넘긴다(tmp_path, wired, caplog):
    with caplog.at_level(logging.WARNING):
        out, steps = _go(tmp_path, responses={}, texts=None)
    # 모델을 부르지 않고, 결과도 없다. 넘긴 이유는 단계마다 남는다
    assert "run_f3" not in out.results and "run_f4" not in out.results
    assert list(out.skipped) == ["run_f3", "run_f2", "run_f4"]
    assert out.skipped["run_f3"].startswith("input_unverified")
    assert out.skipped["run_f4"].startswith("input_unverified")
    recs = {r.tool_name: r for r in steps.records}
    for name in ("run_f3", "run_f4"):
        assert recs[name].outcome == "skipped" and recs[name].result_status == "unverified"
        assert recs[name].skipped_reason == out.skipped[name]
        assert any(name in r.getMessage() for r in caplog.records)
    assert out.trace == ["extract_pages", "read_oa", "cut_to_oa"]


def test_확인_기준일이_없으면_F4만_넘긴다(tmp_path, wired):
    out, _ = _go(tmp_path, checked_on=None)
    assert isinstance(out.results["run_f3"], F3Result)
    assert list(out.skipped) == ["run_f2", "run_f4"]
    assert (
        out.skipped["run_f4"].startswith("input_unverified")
        and "checked_on" in (out.skipped["run_f4"])
    )


def test_청구항_판이_확인되지_않았으면_F3_결과가_input_unverified로_남는다(tmp_path, wired):
    out, _ = _go(tmp_path, texts=_texts(claims_status=bad()))
    f3 = out.results["run_f3"]
    assert f3.units and all(u.status.reason == "input_unverified" for u in f3.units)


def test_agent_모드에서도_지휘가_F3_F4를_골라_부를_수_있다(tmp_path, wired):
    def pick(name):
        return _text({"next_tool": name, "reason": f"{name} 차례"})

    responses = _responses()
    responses["agents.orchestrator"] = [pick(n) for n in ("read_oa", "run_f3", "run_f4", "stop")]
    out, _ = _go(tmp_path, responses, plan="agent")
    assert out.state == "succeeded"
    assert out.trace == ["extract_pages", "read_oa", "cut_to_oa", "run_f3", "run_f4"]
    assert out.skipped == {}


def test_agent_모드에서_넘겼던_단계가_나중에_돌면_넘김_목록에서_빠진다(tmp_path, wired):
    def pick(name):
        return _text({"next_tool": name, "reason": f"{name} 차례"})

    # 처음 run_f4는 F3 결과가 없어 넘겨지고, F3를 돌린 뒤 다시 골라 성공한다
    order = ("read_oa", "run_f4", "run_f3", "run_f4", "stop")
    responses = _responses()
    responses["agents.orchestrator"] = [pick(n) for n in order]
    out, steps = _go(tmp_path, responses, plan="agent")
    assert out.state == "succeeded"
    assert "run_f4" in out.results and "run_f4" not in out.skipped
    # 단계 기록(이력)에는 넘겼던 줄이 그대로 남는다
    assert any(r.tool_name == "run_f4" and r.outcome == "skipped" for r in steps.records)
