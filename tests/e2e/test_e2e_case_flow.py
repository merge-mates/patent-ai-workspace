"""끝에서 끝까지(E2E) 테스트: 사건 하나가 F1 → F3 → F2(넘김) → F4로 돈다 (이슈 #166 T3).

네트워크·API 키·DB 없음. 확인 명령: `uv run pytest -k e2e`
- core 단계(지금 돈다): 지어낸 통지서 하나(tests/fixtures/e2e/)를 진짜 F1 코드(read_oa 규칙+모델
  합치기)로 읽고, 그 결과가 그대로 F3·F4 입력으로 이어진다. #180의 한 바퀴 테스트는 read_oa 자리에
  F4 fixture의 OA를 끼웠는데, 여기서는 끼우지 않는다. 바꿔 끼우는 것은 두 곳뿐이다:
  extract_pages(한글 PDF를 테스트에서 못 만들어 쪽 글자 fixture로)와 F3 검색 자원(DB·임베딩 대신
  메모리 저장소). 모델 답은 가짜 응답(FakeTransport).
- 통지서는 F4 fixture 사건(fixtures/f4/case_basic.json)과 같은 사건으로 지었다: 청구항 1~3,
  진보성(청구항 1·2, D1) + 명확성(청구항 2 '적당한 간격'). 그래서 F3·F4 가짜 응답을 같이 쓴다.
- 서버 단계(올리기 → 실행 → 폴링 → 다시 열기)는 아래 test_server_* 에 기대하는 모양만 적어 두고
  건너뛴다. run_case를 서버 실행기에 잇는 것, F3·F4 결과 저장·다시 열기 API가 아직 없다.
"""

from pathlib import Path

import pytest

from patent_ai.core.agents.orchestrator import CaseInput, run_case
from patent_ai.core.agents.steps import MemoryStepRecorder
from patent_ai.core.f3_claim_compare import run as f3_run
from patent_ai.core.f3_claim_compare.result import F3Result
from patent_ai.core.f4_response_draft.result import F4Output
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.common import StatusValue
from patent_ai.core.schemas.document import PageText
from patent_ai.core.schemas.oa_result import OAResult

# F3·F4 가짜 응답과 실행 입력 글자는 #180 한 바퀴 테스트와 같은 것을 쓴다 (같은 사건이라 한 곳에)
from tests.core.agents.test_fixed_order_f3_f4 import CHECKED_ON, _real_config, _responses, _texts
from tests.core.f3 import scenario

ROOT = Path(__file__).resolve().parents[2]
E2E = ROOT / "tests" / "fixtures" / "e2e"


class _Store:
    """같은 OA·같은 사건이 없는 새 사건."""

    def find_oa(self, application_number, dispatch_number):
        return None

    def find_case(self, application_number):
        return None


def _read_oa_answer() -> TransportResponse:
    return TransportResponse((E2E / "llm" / "read_oa.json").read_text("utf-8"), 100, 50)


@pytest.fixture
def offline(monkeypatch):
    """PDF 글자 읽기와 F3 검색 자원만 바꿔 끼운다 (read_oa·F3·F4 코드는 진짜)."""
    pages = PageText.model_validate_json((E2E / "notice.pages.json").read_text("utf-8"))
    monkeypatch.setattr("patent_ai.core.f1_oa_reader.pages.extract_pages", lambda p, d: pages)
    monkeypatch.setattr(
        f3_run, "make_search_resources", lambda config, ctx: (scenario.searcher(), scenario.REPO)
    )


def _run(tmp_path, responses):
    transport = FakeTransport(responses)
    recorder = MemoryRecorder()
    ctx = RunContext(run_id="r_1", budget=CallBudget(), recorder=recorder, transport=transport)
    case = CaseInput(
        case_id="c_1",
        oa_document=tmp_path / "oa.pdf",
        oa_document_id="d_1",
        texts=_texts(),
        checked_on=CHECKED_ON,
    )
    steps = MemoryStepRecorder()
    # 저장소 설정(config/orchestrator.yaml)의 순서 그대로, plan만 fixed_order
    out = run_case(case, "oa_1", "r_1", _Store(), _real_config(tmp_path), ctx=ctx, steps=steps)
    return out, steps, recorder


def _all_responses() -> dict:
    return {"f1.read_oa": [_read_oa_answer()], **_responses()}


def test_e2e_한_사건이_F1부터_F4까지_돌고_F2는_넘긴_이유가_남는다(tmp_path, offline):
    out, steps, _ = _run(tmp_path, _all_responses())

    assert out.state == "succeeded" and out.error is None
    assert out.trace == ["extract_pages", "read_oa", "cut_to_oa", "run_f3", "run_f4"]
    assert [(r.tool_name, r.outcome) for r in steps.records] == [
        ("extract_pages", "ok"),
        ("read_oa", "ok"),
        ("cut_to_oa", "ok"),
        ("run_f3", "ok"),
        ("run_f2", "skipped"),
        ("run_f4", "ok"),
    ]
    # F2는 결과 없이 넘긴 이유만 (성공으로 숨기지 않는다)
    assert "run_f2" not in out.results
    assert list(out.skipped) == ["run_f2"] and "tool_missing" in out.skipped["run_f2"]


def test_e2e_F1_결과가_원문_대조된_채_F3_F4로_이어진다(tmp_path, offline):
    out, _, _ = _run(tmp_path, _all_responses())
    oa, f3, f4 = out.results["read_oa"], out.results["run_f3"], out.results["run_f4"]

    # F1: 진짜 read_oa가 통지서를 읽어 모든 칸을 원문 대조했다
    assert isinstance(oa, OAResult) and oa.status.value == StatusValue.CONFIRMED
    assert [(r.no, r.article.value, r.claims.value) for r in oa.rejections] == [
        (1, "29-2", [1, 2]),
        (2, "42-4-2", [2]),
    ]
    assert [(c.claim, c.rejection, c.clarity_terms) for c in oa.claim_rows] == [
        (1, 1, []),
        (2, 1, []),
        (2, 2, ["적당한 간격"]),
    ]
    # F3·F4: 같은 OA의 결과이고, 판단 단위가 F1 거절이유에서 나왔다
    assert isinstance(f3, F3Result) and isinstance(f4, F4Output)
    assert f3.oa_id == f4.oa_id == oa.oa_id == "oa_1"
    assert [u.unit_id for u in f3.units] == ["oa_1:29-2:c1", "oa_1:42-4-2:c2"]
    assert f3.comparisons and f3.clarity_reviews
    assert [r.unit_id for r in f3.clarity_reviews] == ["oa_1:42-4-2:c2"]
    assert f4.directions and f4.drafts


def test_e2e_기록된_응답만_쓰고_모델_호출이_실행에_쌓인다(tmp_path, offline):
    responses = _all_responses()
    out, _, recorder = _run(tmp_path, responses)
    assert out.state == "succeeded"
    # 모든 호출이 이 실행 이름으로 기록되고, 실패·상한 초과가 없다
    assert recorder.records and all(r.run_id == "r_1" for r in recorder.records)
    assert {r.outcome for r in recorder.records} == {"ok"}
    # F1은 한 번에 통과 (지휘는 fixed_order라 모델을 안 부른다)
    steps_called = [r.step for r in recorder.records]
    assert steps_called.count("f1.read_oa") == 1
    assert not any(s.startswith("agents.") for s in steps_called)


def test_e2e_F1_모델_답이_두_번_검사에_떨어지면_failed로_끝나고_뒤_단계는_돌지_않는다(
    tmp_path, offline
):
    broken = TransportResponse("JSON 아님", 10, 10)
    responses = {**_all_responses(), "f1.read_oa": [broken, broken]}
    out, steps, _ = _run(tmp_path, responses)

    assert out.state == "failed"
    assert out.error["code"] == "ModelOutputInvalid" and out.error["message"]
    assert not {"read_oa", "run_f3", "run_f4"} & set(out.results)
    assert (steps.records[-1].tool_name, steps.records[-1].outcome) == ("read_oa", "failed")


# ---- 서버 단계: 기대하는 모양 (docs/api/README.md). 빈칸이 채워지면 skip을 지운다 ----
SERVER_GAPS = (
    "서버 E2E 빈칸: (1) run_case를 실행기(#187 core/runs/executor.py)에 잇는 실행기, "
    "(2) F3·F4 결과 저장 + GET /oas/{id}/units·comparisons·clarity-reviews·directions·drafts, "
    "(3) 사건 자료에서 CaseInput.texts(OA 당시 청구항·명세서)를 꺼내는 길"
)


@pytest.mark.skip(reason=SERVER_GAPS)
def test_e2e_server_올리기_실행_폴링_다시_열기(tmp_path, offline):  # pragma: no cover
    """올리기 → 실행 → 폴링 → 결과 받기 → 다시 열기. 요청·응답 모양은 docs/api/README.md."""
    from fastapi.testclient import TestClient

    from patent_ai.api.main import app

    client = TestClient(app)
    pdf = (tmp_path / "oa.pdf").write_bytes(b"%PDF-1.4 e2e") and (tmp_path / "oa.pdf")
    made = client.post("/cases", files={"file": ("oa.pdf", pdf.read_bytes(), "application/pdf")})
    assert made.status_code == 200
    ids = made.json()
    case_id, oa_id, run_id = ids["case_id"], ids["oa_id"], ids["run_id"]

    # 폴링: 화면은 GET /runs/{id}만 본다. 실패를 succeeded로 돌려주지 않는다
    for _ in range(50):
        run = client.get(f"/runs/{run_id}").json()
        if run["state"] not in ("queued", "running"):
            break
    assert run["state"] == "succeeded", run
    assert [s["step"] for s in run["skipped_steps"]] == ["run_f2"]
    assert [w["code"] for w in run["warnings"]] == ["step_skipped"]

    def results() -> dict:
        names = ("oa-result", "units", "comparisons", "clarity-reviews", "directions", "drafts")
        got = {n: client.get(f"/oas/{oa_id}/{n}") for n in names}
        assert {n: r.status_code for n, r in got.items()} == dict.fromkeys(names, 200)
        return {n: r.json() for n, r in got.items()}

    first = results()
    # F2는 넘겨서 결과가 없다: 404 result_not_ready가 아니라 이유가 붙은 빈 목록이어야 한다
    legal = client.get(f"/oas/{oa_id}/legal-evidence")
    assert legal.status_code == 200 and legal.json().get("empty_reason")

    # 다시 열기: 사건 → OA 목록 → latest_run → 같은 결과
    case = client.get(f"/cases/{case_id}").json()
    assert oa_id in [o["oa_id"] for o in case["oas"]]
    oa = client.get(f"/oas/{oa_id}").json()
    assert oa["latest_run"]["run_id"] == run_id and oa["latest_run"]["state"] == "succeeded"
    assert results() == first
