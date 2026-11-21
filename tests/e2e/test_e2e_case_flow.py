"""끝에서 끝까지(E2E) 테스트: 사건 하나가 F1 → F3 → F2(넘김) → F4로 돈다 (이슈 #166 T3).

네트워크·API 키·DB 없음. 확인 명령: `uv run pytest -k e2e`
- core 단계(지금 돈다): 지어낸 통지서 하나(tests/fixtures/e2e/)를 진짜 F1 코드(read_oa 규칙+모델
  합치기)로 읽고, 그 결과가 그대로 F3·F4 입력으로 이어진다. #180의 한 바퀴 테스트는 read_oa 자리에
  F4 fixture의 OA를 끼웠는데, 여기서는 끼우지 않는다. 바꿔 끼우는 것은 두 곳뿐이다:
  extract_pages(한글 PDF를 테스트에서 못 만들어 쪽 글자 fixture로)와 F3 검색 자원(DB·임베딩 대신
  메모리 저장소). 모델 답은 기록된 응답(FakeTransport).
- 통지서는 F4 fixture 사건(fixtures/f4/case_basic.json)과 같은 사건으로 지었다: 청구항 1~3,
  진보성(청구항 1·2, D1) + 명확성(청구항 2 '적당한 간격'). 그래서 F3·F4 기록된 응답을 같이 쓴다.
- 서버 단계(올리기 → 실행 → 폴링 → 다시 열기)는 아래 test_e2e_server_*: 진짜 앱·실행기 위에서
  같은 사건을 돌린다. 저장소는 메모리, 실행은 그 자리에서 바로.
"""

from pathlib import Path

import pytest

from patent_ai.core.agents.orchestrator import CaseInput, run_case
from patent_ai.core.agents.steps import MemoryStepRecorder
from patent_ai.core.cases.run_inputs import RunInputNotFound
from patent_ai.core.cases.store import InMemoryCaseAppStore
from patent_ai.core.f3_claim_compare import run as f3_run
from patent_ai.core.f3_claim_compare.result import F3Result
from patent_ai.core.f4_response_draft.result import F4Output
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.common import StatusValue
from patent_ai.core.schemas.document import PageText
from patent_ai.core.schemas.oa_result import OAResult
from tests.core.f3 import scenario

# F3·F4 기록된 응답과 실행 입력 글자는 #180 한 바퀴 테스트와 같은 것 (같은 사건이라 한 곳에)
from tests.core.run_case_app import NewCase, RunCaseApp
from tests.core.run_case_fakes import CHECKED_ON, real_config, responses, texts

ROOT = Path(__file__).resolve().parents[2]
E2E = ROOT / "tests" / "fixtures" / "e2e"


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
        texts=texts(),
        checked_on=CHECKED_ON,
    )
    steps = MemoryStepRecorder()
    # 저장소 설정(config/orchestrator.yaml)의 순서 그대로, plan만 fixed_order
    out = run_case(case, "oa_1", "r_1", NewCase(), real_config(tmp_path), ctx=ctx, steps=steps)
    return out, steps, recorder


def _all_responses() -> dict:
    return {"f1.read_oa": [_read_oa_answer()], **responses()}


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
    out, _, recorder = _run(tmp_path, _all_responses())
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
    out, steps, _ = _run(tmp_path, {**_all_responses(), "f1.read_oa": [broken, broken]})

    assert out.state == "failed"
    assert out.error["code"] == "ModelOutputInvalid" and out.error["message"]
    assert not {"read_oa", "run_f3", "run_f4"} & set(out.results)
    assert (steps.records[-1].tool_name, steps.records[-1].outcome) == ("read_oa", "failed")


# ---- 서버 단계: 올리기 → 실행 → 폴링 → 다시 열기 (요청·응답 모양은 docs/api/README.md) ----
# 앱은 진짜 라우터·진짜 실행기(RunCaseExecutor)·진짜 run_case다. 바꿔 끼우는 것은
# 저장소(Postgres 대신 메모리), 실행 방법(백그라운드 스레드 대신 그 자리에서 바로),
# 모델 전송층(기록된 응답), 실행 입력 글자(texts: #205가 저장된 청구항 판에서 만든다.
# 여기서는 위 core 단계와 같은 글자를 준다)뿐이다.


class _MemoryRunInputs:
    """PostgresRunInputSource 대신: 올린 OA의 사건·문서로 실행 입력을 만든다.

    메모리 저장소엔 파일 경로가 없어 oa_document는 지어 준다 (글자 읽기는 offline이 바꿔 끼운다).
    올린 파일이 실행기까지 가는지는 db 테스트(tests/core/cases/test_run_inputs_db.py)가 본다.
    """

    def __init__(self, cases: InMemoryCaseAppStore, upload_dir: Path) -> None:
        self._cases = cases
        self._upload_dir = upload_dir

    def case_input(self, oa_id: str) -> CaseInput:
        oa = self._cases.get_oa(oa_id)
        if oa is None:
            raise RunInputNotFound(oa_id)
        return CaseInput(
            case_id=oa.case_id,
            oa_document=self._upload_dir / "oa.pdf",
            oa_document_id=oa.document_id,
            texts=texts(),
        )


class _Server(RunCaseApp):
    """서버 E2E용 앱: 모델 호출 기록을 실행끼리 하나로 모아 밖에서 본다."""

    def __init__(self, tmp_path: Path, answers: dict) -> None:
        self.recorder = MemoryRecorder()
        transport = FakeTransport(answers)
        super().__init__(
            tmp_path,
            make_inputs=lambda cases: _MemoryRunInputs(cases, tmp_path),
            make_ctx=lambda run_id: RunContext(
                run_id=run_id, budget=CallBudget(), recorder=self.recorder, transport=transport
            ),
        )

    def uploaded(self) -> dict:
        res = self.client.post("/cases", files={"file": ("oa.pdf", PDF, "application/pdf")})
        assert res.status_code == 200, res.text
        return res.json()

    def poll(self, run_id: str) -> dict:
        # 화면은 GET /runs/{id}만 본다. 실패를 succeeded로 돌려주지 않는다
        for _ in range(50):
            run = self.client.get(f"/runs/{run_id}").json()
            if run["state"] not in ("queued", "running"):
                return run
        raise AssertionError(f"실행이 끝나지 않음: {run}")


PDF = b"%PDF-1.4 e2e"
RESULTS = ("oa-result", "units", "comparisons", "clarity-reviews", "directions", "drafts")


def test_e2e_server_올리기_실행_폴링_다시_열기(tmp_path, offline):
    server = _Server(tmp_path, _all_responses())
    client = server.client
    ids = server.uploaded()
    case_id, oa_id, run_id = ids["case_id"], ids["oa_id"], ids["run_id"]

    run = server.poll(run_id)
    assert run["state"] == "succeeded", run
    assert run["error"] is None
    # F2는 넘긴 이유와 함께 남는다 (성공으로 숨기지 않는다)
    assert [s["step"] for s in run["skipped_steps"]] == ["run_f2"]
    assert [w["code"] for w in run["warnings"]] == ["step_skipped"]

    def results() -> dict:
        got = {n: client.get(f"/oas/{oa_id}/{n}") for n in RESULTS}
        assert {n: r.status_code for n, r in got.items()} == dict.fromkeys(RESULTS, 200)
        return {n: r.json() for n, r in got.items()}

    first = results()
    # 저장된 것이 이 실행의 F1·F3·F4 결과다 (빈 목록이 아니다)
    assert first["oa-result"]["run_id"] == run_id
    for name in RESULTS[1:]:
        assert first[name]["run_id"] == run_id and first[name]["result"], name
    assert [u["unit_id"] for u in first["units"]["result"]] == [
        f"{oa_id}:29-2:c1",
        f"{oa_id}:42-4-2:c2",
    ]
    # F2는 넘겨서 결과가 없다: 404 result_not_ready가 아니라 이유가 붙은 빈 목록이다
    legal = client.get(f"/oas/{oa_id}/legal-evidence")
    assert legal.status_code == 200
    assert legal.json()["result"] == [] and legal.json()["empty_reason"]

    # 다시 열기: 사건 → OA 목록 → latest_run → 같은 결과
    case = client.get(f"/cases/{case_id}").json()
    assert oa_id in [o["oa_id"] for o in case["oas"]]
    oa = client.get(f"/oas/{oa_id}").json()
    assert oa["latest_run"]["run_id"] == run_id and oa["latest_run"]["state"] == "succeeded"
    assert results() == first
    # 모델 호출은 모두 이 실행 이름으로, 기록된 응답만 썼다
    assert server.recorder.records and {r.run_id for r in server.recorder.records} == {run_id}


def test_e2e_server_F1이_실패하면_failed와_이유가_남고_결과는_없다(tmp_path, offline):
    broken = TransportResponse("JSON 아님", 10, 10)
    server = _Server(tmp_path, {**_all_responses(), "f1.read_oa": [broken, broken]})
    ids = server.uploaded()

    run = server.poll(ids["run_id"])
    assert run["state"] == "failed"
    assert run["error"]["code"] == "step_failed"
    assert run["error"]["message"] == "read_oa: 실패 (ModelOutputInvalid)"
    for name in RESULTS:
        res = server.client.get(f"/oas/{ids['oa_id']}/{name}")
        assert (res.status_code, res.json()["code"]) == (404, "result_not_ready"), name
