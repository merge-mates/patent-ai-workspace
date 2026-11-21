"""실행 엔드포인트 API 테스트 (#57 T3): TestClient + 메모리 fake + 가짜 실행기. DB 없음.

launcher는 그 자리에서 바로 도는 것을 끼운다 (진짜 앱은 백그라운드 스레드).
"""

import pytest
from fastapi.testclient import TestClient

from patent_ai.api import deps
from patent_ai.api.deps import (
    get_cancel_registry,
    get_case_unit,
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
from patent_ai.core.runs.run_case_executor import RunCaseExecutor
from patent_ai.core.runs.state import RunError, RunState
from tests.core.runs.fake_executor import (
    cancelling_step,
    load_oa_result,
    raising_step,
    skipping_step,
    waiting_step,
)

PDF = b"%PDF-1.7\nA"


class FakeUnit:
    def __init__(self, store):
        self.store = store

    def commit(self):
        pass

    def rollback(self):
        pass


class Env:
    """한 테스트의 앱과 공유 저장소. steps를 바꿔 가짜 실행기 시나리오를 고른다."""

    def __init__(self, tmp_path):
        self.runs = InMemoryRunStore()
        self.cases = InMemoryCaseAppStore(runs=self.runs)
        self.registry = CancelRegistry()
        self.sink = InMemoryOAResultStore(self.runs)
        self.steps: list[Step] = [Step("OA 읽는 중", lambda: None)]
        self.launch_enabled = True
        self.launched: list[tuple[str, str]] = []
        unit = FakeUnit(self.cases)
        app = create_app(startup_store=self.runs)
        app.dependency_overrides[get_case_unit] = lambda: unit
        app.dependency_overrides[get_upload_dir] = lambda: tmp_path
        app.dependency_overrides[get_run_status_store] = lambda: self.runs
        app.dependency_overrides[get_cancel_registry] = lambda: self.registry
        app.dependency_overrides[get_run_executor] = self._fake_executor
        app.dependency_overrides[get_run_launcher] = lambda: self._launch
        self.app = app
        self.client = TestClient(app, raise_server_exceptions=False)

    def _fake_executor(self):
        return StepRunExecutor(
            store=self.runs,
            registry=self.registry,
            sink=self.sink,
            steps=self.steps,
            get_result=load_oa_result,
        )

    def _launch(self, run_id, oa_id):
        """그 자리에서 바로 돈다. launch_enabled가 꺼져 있으면 queued로 둔다."""
        self.launched.append((run_id, oa_id))
        if self.launch_enabled:
            self._fake_executor().execute(run_id, oa_id)

    def upload(self):
        return self.client.post("/cases", files={"file": ("oa.pdf", PDF, "application/pdf")}).json()


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def test_만들기_폴링_succeeded_결과가_저장된다(env):
    created = env.upload()  # 업로드가 만든 실행이 바로 돈다
    res = env.client.get(f"/runs/{created['run_id']}")
    assert res.status_code == 200
    body = res.json()
    assert body == {
        "run_id": created["run_id"],
        "oa_id": created["oa_id"],
        "state": "succeeded",
        "current_step": "OA 읽는 중",
        "waiting_for": None,
        "error": None,
        "skipped_steps": [],
        "warnings": [],
    }
    assert [(o, r) for o, r, _ in env.sink.saved] == [(created["oa_id"], created["run_id"])]


def test_POST_oas_runs는_새_실행을_만들고_돌린다(env):
    created = env.upload()  # 첫 실행은 succeeded로 끝남
    res = env.client.post(f"/oas/{created['oa_id']}/runs")
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"run_id"} and body["run_id"] != created["run_id"]
    assert (body["run_id"], created["oa_id"]) in env.launched
    assert env.client.get(f"/runs/{body['run_id']}").json()["state"] == "succeeded"


def test_실패하면_failed와_이유가_응답에_있다(env):
    env.steps = [raising_step("OA 읽는 중", RuntimeError("PDF가 깨짐"))]
    created = env.upload()
    body = env.client.get(f"/runs/{created['run_id']}").json()
    assert body["state"] == "failed"
    assert body["error"]["code"] == "step_failed"
    assert "RuntimeError" in body["error"]["message"]
    assert "PDF가 깨짐" not in body["error"]["message"]  # 예외 원문은 로그에만
    assert env.sink.saved == []  # 조용히 성공으로 끝나지 않는다


def test_queued_취소는_바로_cancelled(env):
    env.launch_enabled = False  # 아무것도 안 해서 queued로 남는다
    created = env.upload()
    assert env.client.get(f"/runs/{created['run_id']}").json()["state"] == "queued"
    res = env.client.post(f"/runs/{created['run_id']}/cancel")
    assert res.status_code == 200 and res.json()["state"] == "cancelled"
    assert env.client.get(f"/runs/{created['run_id']}").json()["state"] == "cancelled"


def test_도는_중_취소하면_멈추고_cancelled가_남고_결과는_저장되지_않는다(env):
    log: list[str] = []
    env.launch_enabled = False
    created = env.upload()
    run_id = created["run_id"]
    # 단계 안에서 취소를 요청한다 (취소 엔드포인트와 같은 request_cancel 경로: running은 표시만)
    env.steps = [
        Step("OA 읽는 중", lambda: env.client.post(f"/runs/{run_id}/cancel") and None),
        cancelling_step("거절이유 정리 중", env.registry, run_id, log),
    ]
    env._fake_executor().execute(run_id, created["oa_id"])
    assert env.client.get(f"/runs/{run_id}").json()["state"] == "cancelled"
    assert env.sink.saved == []
    assert log == []  # 취소 뒤 다음 단계는 돌지 않았다


def test_running_취소_응답은_state_그대로(env):
    env.launch_enabled = False
    created = env.upload()
    env.runs.transition(created["run_id"], RunState.RUNNING)
    res = env.client.post(f"/runs/{created['run_id']}/cancel")
    assert res.status_code == 200 and res.json()["state"] == "running"
    assert env.registry.is_requested(created["run_id"])


def test_waiting_for_human_취소는_바로_cancelled(env):
    env.steps = [waiting_step("사람 확인", "reviewer")]
    created = env.upload()
    body = env.client.get(f"/runs/{created['run_id']}").json()
    assert body["state"] == "waiting_for_human" and body["waiting_for"] == "reviewer"
    res = env.client.post(f"/runs/{created['run_id']}/cancel")
    assert res.status_code == 200 and res.json()["state"] == "cancelled"


def test_run_case_앱_기본_실행기는_지휘_실행기이고_취소_결과_저장소를_API와_같이_쓴다():
    # DB에 붙지 않는다 (엔진·세션 만드는 함수만 만들고 연결은 처음 쓸 때)
    executor = deps.get_run_executor()
    assert isinstance(executor, RunCaseExecutor)
    assert executor is deps.get_run_executor()  # 앱에 하나: 잠금 하나로 한 번에 하나만 돈다
    # 취소 API가 쓰는 표시와 같아야 취소가 실행기에 닿는다
    assert executor._registry is deps.get_cancel_registry()
    assert executor._store is deps.get_run_status_store()
    # 결과 API가 읽는 저장소에 쓴다
    assert executor._oa_results is deps.get_oa_result_store()
    assert executor._step_results is deps.get_step_result_store()
    assert executor._config_path == deps.ORCHESTRATOR_CONFIG and executor._config_path.exists()


def test_켜질_때_running_queued는_server_restarted로_waiting은_그대로(tmp_path):
    env = Env(tmp_path)
    env.launch_enabled = False
    a = env.upload()
    b = env.client.post(
        f"/cases/{a['case_id']}/oas", files={"file": ("b.pdf", b"%PDF-1.7\nB", "x/pdf")}
    ).json()
    c = env.client.post(
        f"/cases/{a['case_id']}/oas", files={"file": ("c.pdf", b"%PDF-1.7\nC", "x/pdf")}
    ).json()
    env.runs.transition(b["run_id"], RunState.RUNNING)
    env.runs.transition(c["run_id"], RunState.RUNNING)
    env.runs.transition(c["run_id"], RunState.WAITING_FOR_HUMAN, waiting_for="reviewer")
    with TestClient(env.app):  # with로 열어야 lifespan(켜질 때 정리)이 돈다
        pass
    for run_id in (a["run_id"], b["run_id"]):
        body = env.runs.get_status(run_id)
        assert body.state == RunState.FAILED and body.error["code"] == "server_restarted"
    assert env.runs.get_status(c["run_id"]).state == RunState.WAITING_FOR_HUMAN


def test_없는_것은_404(env):
    for res, code in [
        (env.client.get("/runs/r_없음"), "run_not_found"),
        (env.client.post("/runs/r_없음/cancel"), "run_not_found"),
        (env.client.post("/oas/oa_없음/runs"), "oa_not_found"),
    ]:
        assert res.status_code == 404
        assert set(res.json()) == {"code", "message"} and res.json()["code"] == code


def test_끝난_실행_취소는_409(env):
    created = env.upload()  # succeeded
    res = env.client.post(f"/runs/{created['run_id']}/cancel")
    assert res.status_code == 409
    assert set(res.json()) == {"code", "message"}
    assert res.json()["code"] == "run_already_finished"


@pytest.mark.parametrize("state", [RunState.QUEUED, RunState.RUNNING, RunState.WAITING_FOR_HUMAN])
def test_진행_중_실행이_있으면_실행_만들기는_409(env, state):
    env.launch_enabled = False
    created = env.upload()  # queued
    if state == RunState.RUNNING:
        env.runs.transition(created["run_id"], RunState.RUNNING)
    if state == RunState.WAITING_FOR_HUMAN:
        env.runs.transition(created["run_id"], RunState.RUNNING)
        env.runs.transition(created["run_id"], state, waiting_for="reviewer")
    res = env.client.post(f"/oas/{created['oa_id']}/runs")
    assert res.status_code == 409
    assert set(res.json()) == {"code", "message"} and res.json()["code"] == "run_in_progress"
    assert len(env.launched) == 1  # 새 실행은 만들지도 돌리지도 않았다


def test_끝난_뒤에는_다시_실행을_만들_수_있다(env):
    env.launch_enabled = False
    created = env.upload()
    env.runs.transition(created["run_id"], RunState.FAILED, error=RunError("x", "y"))
    assert env.client.post(f"/oas/{created['oa_id']}/runs").status_code == 200


def _boom_launcher(run_id, oa_id):
    raise RuntimeError("스레드를 못 띄움")


def test_launch가_실패하면_그_실행은_failed_launch_failed로_남고_다시_만들_수_있다(env):
    env.launch_enabled = False
    created = env.upload()
    env.runs.transition(created["run_id"], RunState.FAILED, error=RunError("x", "y"))
    env.app.dependency_overrides[get_run_launcher] = lambda: _boom_launcher
    res = env.client.post(f"/oas/{created['oa_id']}/runs")
    assert res.status_code == 500 and set(res.json()) == {"code", "message"}
    latest = env.cases.get_oa(created["oa_id"]).latest_run
    status = env.runs.get_status(latest.id)
    assert latest.id != created["run_id"]
    assert status.state == RunState.FAILED and status.error["code"] == "launch_failed"
    # queued로 남지 않았으니 이 OA는 409로 막히지 않는다
    env.app.dependency_overrides[get_run_launcher] = lambda: env._launch
    assert env.client.post(f"/oas/{created['oa_id']}/runs").status_code == 200


def test_업로드_뒤_launch가_실패해도_실행이_queued로_남지_않는다(env):
    env.app.dependency_overrides[get_run_launcher] = lambda: _boom_launcher
    res = env.client.post("/cases", files={"file": ("oa.pdf", PDF, "application/pdf")})
    assert res.status_code == 500
    (row,) = [env.cases.get_oa(o).latest_run for o in env.cases._oas]
    assert env.runs.get_status(row.id).error["code"] == "launch_failed"


def test_업로드_파일_마무리가_실패해도_실행이_queued로_남지_않는다(env, monkeypatch):
    env.launch_enabled = False

    def broken_finalize(tmp, target):
        raise OSError("디스크 오류")

    monkeypatch.setattr("patent_ai.core.cases.upload.finalize", broken_finalize)
    res = env.client.post("/cases", files={"file": ("oa.pdf", PDF, "application/pdf")})
    assert res.status_code == 500 and res.json()["code"] == "upload_failed"
    (row,) = [env.cases.get_oa(o).latest_run for o in env.cases._oas]
    status = env.runs.get_status(row.id)
    assert status.state == RunState.FAILED and status.error["code"] == "launch_failed"
    assert env.launched == []  # 실행기에는 넘기지 않았다


def test_넘긴_단계가_있으면_succeeded와_skipped_steps_warnings가_보인다(env):
    env.steps = [
        skipping_step("인용문헌 조회", "자료 없음"),
        Step("거절이유 정리 중", lambda: None),
    ]
    created = env.upload()
    body = env.client.get(f"/runs/{created['run_id']}").json()
    assert body["state"] == "succeeded"
    assert body["skipped_steps"] == [{"step": "인용문헌 조회", "reason": "자료 없음"}]
    assert body["warnings"] == [
        {"code": "step_skipped", "message": "인용문헌 조회 단계를 건너뜀: 자료 없음"}
    ]
    assert len(env.sink.saved) == 1  # 넘겨도 결과는 저장된다


def test_넘긴_단계가_없으면_skipped_steps_warnings는_빈_목록(env):
    created = env.upload()
    body = env.client.get(f"/runs/{created['run_id']}").json()
    assert body["skipped_steps"] == [] and body["warnings"] == []


def test_취소_응답도_같은_모양으로_넘긴_단계를_준다(env):
    env.steps = [skipping_step("인용문헌 조회", "자료 없음"), waiting_step("사람 확인", "reviewer")]
    created = env.upload()
    res = env.client.post(f"/runs/{created['run_id']}/cancel")
    body = res.json()
    assert body["state"] == "cancelled"
    assert body["skipped_steps"] == [{"step": "인용문헌 조회", "reason": "자료 없음"}]
    assert body["warnings"][0]["code"] == "step_skipped"
