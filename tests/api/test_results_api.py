"""F3·F4 결과 조회 API (이슈 #191 T3). 확인: uv run pytest tests/api -k results_api

진짜 실행기(RunCaseExecutor) + 메모리 저장소 + 기록된 응답. 네트워크·키·DB 없음.
launcher는 그 자리에서 바로 돈다 (진짜 앱은 백그라운드 스레드).
"""

import pytest
from fastapi.testclient import TestClient

from patent_ai.api.deps import (
    get_cancel_registry,
    get_case_unit,
    get_oa_result_store,
    get_run_executor,
    get_run_launcher,
    get_run_status_store,
    get_step_result_store,
    get_upload_dir,
)
from patent_ai.api.main import create_app
from patent_ai.core.agents.orchestrator import CaseInput
from patent_ai.core.cases.results import InMemoryOAResultStore
from patent_ai.core.cases.step_results import InMemoryStepResultStore
from patent_ai.core.cases.store import InMemoryCaseAppStore, InMemoryRunStore
from patent_ai.core.runs.cancel import CancelRegistry
from patent_ai.core.runs.run_case_executor import RunCaseExecutor
from tests.core.run_case_fakes import (
    CHECKED_ON,
    fake_ctx,
    real_config,
    texts,
    wire,
    wire_broken_pdf,
)

PDF = b"%PDF-1.7\nA"
NAMES = ("units", "comparisons", "clarity-reviews", "legal-evidence", "directions", "drafts")


class FakeUnit:
    def __init__(self, store):
        self.store = store

    def commit(self):
        pass

    def rollback(self):
        pass


class _Inputs:
    """메모리 사건 저장소에는 파일 경로가 없어 실행 입력을 지어 준다 (PDF 읽기는 바꿔 끼움)."""

    def __init__(self, tmp_path, with_texts):
        self.tmp_path, self.with_texts = tmp_path, with_texts

    def case_input(self, oa_id):
        return CaseInput(
            case_id="c_1",
            oa_document=self.tmp_path / "oa.pdf",
            oa_document_id="d_1",
            texts=texts() if self.with_texts else None,
        )


class _NewCase:
    def find_oa(self, application_number, dispatch_number):
        return None

    def find_case(self, application_number):
        return None


class Env:
    def __init__(self, tmp_path, with_texts=True):
        self.runs = InMemoryRunStore()
        self.cases = InMemoryCaseAppStore(runs=self.runs)
        self.registry = CancelRegistry()
        self.oa_results = InMemoryOAResultStore(self.runs)
        self.steps = InMemoryStepResultStore()
        self.launch_enabled = True
        self.executor = RunCaseExecutor(
            store=self.runs,
            registry=self.registry,
            oa_results=self.oa_results,
            step_results=self.steps,
            inputs=_Inputs(tmp_path, with_texts),
            cases=_NewCase(),
            config_path=real_config(tmp_path),
            make_ctx=fake_ctx,
            today=lambda: CHECKED_ON,
        )
        unit = FakeUnit(self.cases)
        app = create_app(startup_store=self.runs)
        app.dependency_overrides[get_case_unit] = lambda: unit
        app.dependency_overrides[get_upload_dir] = lambda: tmp_path
        app.dependency_overrides[get_run_status_store] = lambda: self.runs
        app.dependency_overrides[get_cancel_registry] = lambda: self.registry
        app.dependency_overrides[get_oa_result_store] = lambda: self.oa_results
        app.dependency_overrides[get_step_result_store] = lambda: self.steps
        app.dependency_overrides[get_run_executor] = lambda: self.executor
        app.dependency_overrides[get_run_launcher] = lambda: self._launch
        self.client = TestClient(app, raise_server_exceptions=False)

    def _launch(self, run_id, oa_id):
        if self.launch_enabled:
            self.executor.execute(run_id, oa_id)

    def upload(self):
        return self.client.post("/cases", files={"file": ("oa.pdf", PDF, "application/pdf")}).json()

    def get(self, oa_id, name):
        return self.client.get(f"/oas/{oa_id}/{name}")


@pytest.fixture
def env(tmp_path, monkeypatch):
    wire(monkeypatch)
    return Env(tmp_path)


def test_results_api_실행이_끝나면_F3_F4_결과가_같은_실행에서_열린다(env):
    created = env.upload()
    oa_id, run_id = created["oa_id"], created["run_id"]
    assert env.client.get(f"/runs/{run_id}").json()["state"] == "succeeded"
    got = {n: env.get(oa_id, n) for n in NAMES}
    assert {n: r.status_code for n, r in got.items()} == dict.fromkeys(NAMES, 200)
    body = {n: r.json() for n, r in got.items()}
    # 모든 결과가 OA 정리와 같은 실행에서 나온다
    oa_result = env.client.get(f"/oas/{oa_id}/oa-result").json()
    assert {b["run_id"] for b in body.values()} == {oa_result["run_id"]} == {run_id}
    for n in ("units", "comparisons", "clarity-reviews", "directions"):
        assert body[n]["result"] and body[n]["empty_reason"] is None, n
    assert body["drafts"]["result"] is not None and body["drafts"]["legality_notice"]
    assert body["directions"]["rank_notice"]


def test_results_api_넘긴_F2는_빈_목록과_넘긴_이유(env):
    oa_id = env.upload()["oa_id"]
    legal = env.get(oa_id, "legal-evidence")
    assert legal.status_code == 200
    assert legal.json()["result"] == []
    assert legal.json()["empty_reason"].startswith("넘김: tool_missing")


def test_results_api_청구항_판을_못_찾으면_F3_F4는_빈_목록과_input_unverified(
    tmp_path, monkeypatch
):
    wire(monkeypatch)
    env = Env(tmp_path, with_texts=False)
    oa_id = env.upload()["oa_id"]
    for n in ("units", "comparisons", "clarity-reviews", "directions"):
        r = env.get(oa_id, n).json()
        assert r["result"] == [] and r["empty_reason"].startswith("넘김: input_unverified"), n
    drafts = env.get(oa_id, "drafts").json()
    assert drafts["result"] is None and drafts["empty_reason"].startswith("넘김: input_unverified")
    assert drafts["held_units"] == []


def test_results_api_실행_전이면_404_result_not_ready(env):
    env.launch_enabled = False
    oa_id = env.upload()["oa_id"]
    for n in NAMES:
        r = env.get(oa_id, n)
        assert r.status_code == 404 and r.json()["code"] == "result_not_ready", n


def test_results_api_실패한_실행의_결과는_주지_않는다(tmp_path, monkeypatch):
    wire(monkeypatch)
    wire_broken_pdf(monkeypatch, secret="원문")
    env = Env(tmp_path)
    created = env.upload()
    run = env.client.get(f"/runs/{created['run_id']}").json()
    assert run["state"] == "failed" and "원문" not in run["error"]["message"]
    for n in NAMES:
        assert env.get(created["oa_id"], n).status_code == 404, n


def test_results_api_없는_OA면_404_oa_not_found(env):
    for n in NAMES:
        r = env.get("oa_없음", n)
        assert r.status_code == 404 and r.json()["code"] == "oa_not_found", n
