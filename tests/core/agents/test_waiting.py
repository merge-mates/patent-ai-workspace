"""멈추는 조건과 사람 기다림 테스트 (tasks-2.md m1-i2-15 task-3). 진짜 모델 호출 없음."""

import json
from pathlib import Path

from reportlab.pdfgen import canvas

from patent_ai.core.agents.orchestrator import CaseInput, WaitingFor, run_case
from patent_ai.core.agents.steps import MemoryStepRecorder
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "f1"
APP = "10-2099-0000001"
DISPATCH = "9-5-2099-000000001"
# 결과 value는 정답 형식대로 숫자만 (저장소 조회도 이 값으로 함)
APP_VALUE = "1020990000001"
DISPATCH_VALUE = "952099000000001"


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


out_steps: list = []  # 마지막 _go의 단계 기록


def _go(
    tmp_path,
    *,
    with_numbers=True,
    store=None,
    plan="fixed_order",
    max_steps=10,
    dispatch_in_pdf=True,
    responses=None,
):
    pdf = tmp_path / "oa.pdf"
    c = canvas.Canvas(str(pdf))
    # 번호가 있는 통지서 / 번호 글자가 하나도 없는 통지서
    c.drawString(72, 720, f"Application No. {APP}" if with_numbers else "Notice of reasons")
    has_dispatch = with_numbers and dispatch_in_pdf
    c.drawString(72, 700, f"Dispatch No. {DISPATCH}" if has_dispatch else "Please respond")
    c.showPage()
    c.save()
    cfg = tmp_path / "orchestrator.yaml"
    cfg.write_text(
        f"plan: {plan}\nfixed_order: [extract_pages, read_oa]\nmax_steps: {max_steps}\n",
        encoding="utf-8",
    )
    transport = FakeTransport(responses or {"f1.read_oa": [_answer(not with_numbers)]})
    store = store if store is not None else FakeStore()
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    case = CaseInput(case_id="c_new", oa_document=pdf, oa_document_id="d_1", materials=["자료"])
    steps = MemoryStepRecorder()
    out = run_case(case, "oa_1", "r_1", store, cfg, ctx=ctx, steps=steps)
    out_steps[:] = steps.records
    return out


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
    assert ("find_oa", APP_VALUE, DISPATCH_VALUE) in store.calls


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
    assert (out_steps[-1].step_kind, out_steps[-1].tool_name, out_steps[-1].outcome) == (
        "check",
        "check_oa",
        "failed",
    )


def test_같은_OA를_다시_돌리면_중복이_아니라_끝까지_돈다(tmp_path):
    # 저장소가 찾은 OA가 지금 돌리는 OA 자신(oa_1)이면 다시 돌리기다 (POST /oas/{oa_id}/runs)
    out = _go(tmp_path, store=FakeStore(oa=("c_old", "oa_1")))
    assert out.state == "succeeded"
    assert out.error is None
    assert out.case_id == "c_old"
    assert all(r.outcome != "failed" for r in out_steps)


def test_기존_사건의_다음_OA면_최종_case_id가_기존_사건(tmp_path):
    out = _go(tmp_path, store=FakeStore(oa=None, case="c_old"))
    assert out.state == "succeeded"
    assert out.case_id == "c_old"


def test_출원번호가_충돌이면_사람을_기다린다(tmp_path, monkeypatch):
    # 영어 PDF로는 규칙이 번호를 못 읽어 충돌이 안 나므로 출원번호 칸만 충돌로 바꾼다
    from patent_ai.core.f1_oa_reader import read_oa as mod
    from patent_ai.core.schemas.common import Candidate, ExtractedValue, Status, StatusValue

    real = mod.read_oa

    def conflicted(*a, **k):
        r = real(*a, **k)
        bad = ExtractedValue[str](
            status=Status(value=StatusValue.CONFLICT),
            candidates=[
                Candidate[str](value="10-2099-0000001", raw_text="a", page=1, source="rule"),
                Candidate[str](value="10-2099-0000009", raw_text="b", page=1, source="model"),
            ],
        )
        return r.model_copy(update={"application_number": bad})

    monkeypatch.setattr(mod, "read_oa", conflicted)
    out = _go(tmp_path)
    assert out.state == "waiting_for_human"
    assert out.waiting_for == WaitingFor.APPLICATION_NUMBER
    assert "cut_to_oa" not in out.results


def test_발송번호를_모르면_같은_OA인지_몰라_사람을_기다린다(tmp_path):
    store = FakeStore(oa=("c_old", "oa_old"))
    out = _go(tmp_path, dispatch_in_pdf=False, store=store)
    assert out.state == "waiting_for_human"
    assert out.waiting_for == WaitingFor.DISPATCH_NUMBER
    # 필드 추출은 끝까지 했고(거절이유까지 나옴), 멈춘 것은 중복 판정·자동 조회(자르기)뿐이다
    assert "read_oa" in out.results
    assert len(out.results["read_oa"].rejections) > 0
    assert "cut_to_oa" not in out.results
    assert store.calls == []


def test_store가_None이면_ValueError(tmp_path):
    import pytest

    cfg = tmp_path / "o.yaml"
    cfg.write_text("plan: fixed_order\n", encoding="utf-8")
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=FakeTransport({})
    )
    case = CaseInput(case_id="c", oa_document=tmp_path / "x.pdf", oa_document_id="d")
    with pytest.raises(ValueError, match="store"):
        run_case(case, "oa_1", "r_1", None, cfg, ctx=ctx, steps=MemoryStepRecorder())


def _decision(name: str) -> TransportResponse:
    return TransportResponse(json.dumps({"next_tool": name, "reason": "테스트"}), 10, 10)


def test_read_oa_뒤_extract_pages만_되풀이해도_자르기는_이미_돌았다(tmp_path):
    answers = {
        "agents.orchestrator": [_decision("read_oa")] + [_decision("extract_pages")] * 10,
        "f1.read_oa": [_answer(False)],
    }
    out = _go(tmp_path, plan="agent", max_steps=4, responses=answers)
    assert out.state == "failed"
    assert out.error["code"] == "max_steps"
    # read_oa 바로 다음이 자르기 (check_oa는 도구가 아니라 검사 노드라 기록에 없다)
    assert out.trace[:3] == ["extract_pages", "read_oa", "cut_to_oa"]
    assert "cut_to_oa" in out.results
    # 찾아본 범위는 돈 도구 목록
    assert out.searched_scope == out.trace
    assert "extract_pages" in out.error["message"]


def test_정확히_max_steps만큼_돌고_끝났으면_실패가_아니다(tmp_path):
    # extract_pages(1) + read_oa(2) 뒤 stop: 상한과 같아도 성공
    answers = {
        "agents.orchestrator": [_decision("read_oa"), _decision("stop")],
        "f1.read_oa": [_answer(False)],
    }
    out = _go(tmp_path, plan="agent", max_steps=2, responses=answers)
    assert out.state == "succeeded"
    assert out.trace == ["extract_pages", "read_oa", "cut_to_oa"]


def test_read_oa를_두_번_고르면_거부(tmp_path):
    answers = {
        "agents.orchestrator": [_decision("read_oa"), _decision("read_oa")],
        "f1.read_oa": [_answer(False)],
    }
    out = _go(tmp_path, plan="agent", responses=answers)
    assert out.state == "failed"
    assert out.error["code"] == "invalid_tool_choice"


def test_지휘_모델_답이_틀리면_failed(tmp_path):
    bad = TransportResponse("JSON 아님", 10, 10)
    out = _go(tmp_path, plan="agent", responses={"agents.orchestrator": [bad, bad, bad]})
    assert out.state == "failed"
    assert out.error["code"] == "ModelOutputInvalid"


def test_목록_밖_예외는_로그를_남기고_그대로_던진다(tmp_path, monkeypatch, caplog):
    import pytest

    def boom(*a, **k):
        raise RuntimeError("버그")

    monkeypatch.setattr("patent_ai.core.f1_oa_reader.read_oa.read_oa", boom)
    with caplog.at_level("ERROR"), pytest.raises(RuntimeError):
        _go(tmp_path)
    assert "r_1" in caplog.text
    assert "extract_pages" in caplog.text
