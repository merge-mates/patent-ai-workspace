"""OA 정리 결과 받기 API 테스트 (#57 T4): TestClient + 메모리 fake + 가짜 실행기. DB 없음.

succeeded 실행의 결과만 준다. 실행 전·중·실패·취소는 404 result_not_ready.
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
    get_upload_dir,
)
from patent_ai.api.main import create_app
from patent_ai.core.cases.results import InMemoryOAResultStore
from patent_ai.core.cases.store import InMemoryCaseAppStore, InMemoryRunStore
from patent_ai.core.runs.cancel import CancelRegistry
from patent_ai.core.runs.executor import Step, StepRunExecutor
from patent_ai.core.runs.state import RunState
from tests.core.runs.fake_executor import load_oa_result, raising_step

PDF = b"%PDF-1.7\nA"


class FakeUnit:
    def __init__(self, store):
        self.store = store

    def commit(self):
        pass

    def rollback(self):
        pass


class Env:
    def __init__(self, tmp_path):
        self.runs = InMemoryRunStore()
        self.cases = InMemoryCaseAppStore(runs=self.runs)
        self.results = InMemoryOAResultStore(self.runs)
        self.registry = CancelRegistry()
        self.steps: list[Step] = [Step("OA 읽는 중", lambda: None)]
        self.launch_enabled = True
        unit = FakeUnit(self.cases)
        app = create_app(startup_store=self.runs)
        app.dependency_overrides[get_case_unit] = lambda: unit
        app.dependency_overrides[get_upload_dir] = lambda: tmp_path
        app.dependency_overrides[get_run_status_store] = lambda: self.runs
        app.dependency_overrides[get_cancel_registry] = lambda: self.registry
        app.dependency_overrides[get_oa_result_store] = lambda: self.results
        app.dependency_overrides[get_run_executor] = self._executor
        app.dependency_overrides[get_run_launcher] = lambda: self._launch
        self.client = TestClient(app, raise_server_exceptions=False)

    def _executor(self):
        # 결과 받는 곳(sink)은 API가 읽는 저장소와 같은 것
        return StepRunExecutor(
            store=self.runs,
            registry=self.registry,
            sink=self.results,
            steps=self.steps,
            get_result=load_oa_result,
        )

    def _launch(self, run_id, oa_id):
        if self.launch_enabled:
            self._executor().execute(run_id, oa_id)

    def upload(self):
        return self.client.post("/cases", files={"file": ("oa.pdf", PDF, "application/pdf")}).json()

    def rerun(self, oa_id):
        return self.client.post(f"/oas/{oa_id}/runs").json()

    def get_result(self, oa_id):
        return self.client.get(f"/oas/{oa_id}/oa-result")


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def _not_ready(res):
    assert res.status_code == 404
    assert res.json() == {"code": "result_not_ready", "message": res.json()["message"]}


def test_실행_전에는_결과_줄이_없어_result_not_ready(env):
    env.launch_enabled = False  # 아무것도 안 해서 queued로 남는다
    created = env.upload()
    _not_ready(env.get_result(created["oa_id"]))


@pytest.mark.parametrize(
    "state", [RunState.QUEUED, RunState.RUNNING, RunState.WAITING_FOR_HUMAN, RunState.CANCELLED]
)
def test_succeeded가_아닌_실행이_결과를_저장해_둬도_안_준다(env, state):
    # 실제 실행기는 결과를 먼저 저장하고 succeeded로 바꾸므로, 결과 줄이 있는데 아직
    # succeeded가 아닌 순간이 생긴다. 그때 결과를 내주면 안 된다
    env.launch_enabled = False
    created = env.upload()
    run_id = created["run_id"]
    if state != RunState.QUEUED:
        env.runs.transition(run_id, RunState.RUNNING)
    if state == RunState.WAITING_FOR_HUMAN:
        env.runs.transition(run_id, state, waiting_for="reviewer")
    if state == RunState.CANCELLED:
        env.runs.transition(run_id, state)
    assert env.runs.get_status(run_id).state == state
    env.results.save_oa_result(created["oa_id"], run_id, load_oa_result())
    _not_ready(env.get_result(created["oa_id"]))


def test_끝나면_결과가_result에_담겨_온다(env):
    created = env.upload()
    res = env.get_result(created["oa_id"])
    assert res.status_code == 200
    body = res.json()
    expected = load_oa_result()
    assert set(body) == {"oa_id", "run_id", "status", "result"}
    assert body["oa_id"] == created["oa_id"] and body["run_id"] == created["run_id"]
    assert body["status"] == expected.status.value.value == body["result"]["status"]["value"]
    assert body["result"] == expected.model_dump(mode="json")


def test_실패한_실행의_결과는_안_준다(env):
    env.steps = [raising_step("OA 읽는 중", RuntimeError("PDF가 깨짐"))]
    created = env.upload()
    assert env.runs.get_status(created["run_id"]).state == RunState.FAILED
    # 실패한 실행이 결과를 저장해 두었더라도 succeeded가 아니면 안 준다
    env.results.save_oa_result(created["oa_id"], created["run_id"], load_oa_result())
    _not_ready(env.get_result(created["oa_id"]))


def test_두_번_돌리면_나중_succeeded_결과를_준다(env):
    created = env.upload()
    second = env.rerun(created["oa_id"])
    body = env.get_result(created["oa_id"]).json()
    assert body["run_id"] == second["run_id"] != created["run_id"]


def test_나중_실행이_실패하면_앞_succeeded_결과가_남는다(env):
    created = env.upload()
    env.steps = [raising_step("OA 읽는 중", RuntimeError("x"))]
    failed = env.rerun(created["oa_id"])
    assert env.runs.get_status(failed["run_id"]).state == RunState.FAILED
    assert env.get_result(created["oa_id"]).json()["run_id"] == created["run_id"]


def test_없는_OA는_404_oa_not_found(env):
    res = env.get_result("oa_없음")
    assert res.status_code == 404
    assert set(res.json()) == {"code", "message"} and res.json()["code"] == "oa_not_found"
