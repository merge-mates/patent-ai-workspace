"""진짜 앱(라우터 + RunCaseExecutor + run_case)을 메모리 저장소로 조립하는 도움 함수.

서버 쪽 테스트(결과 API, 서버 E2E)가 같이 쓴다. deps에 의존성이 늘면 여기 한 곳만 고친다.
바꿔 끼우는 것: 저장소(Postgres 대신 메모리), 실행 방법(백그라운드 스레드 대신 그 자리에서 바로),
실행 입력(make_inputs), 모델 호출 맥락(make_ctx).
네트워크·키·DB 없음. 앱 코드에서 import하지 않는다.
"""

from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from patent_ai.api.deps import (
    get_cancel_registry,
    get_case_repository_unit,
    get_case_unit,
    get_oa_result_store,
    get_run_executor,
    get_run_launcher,
    get_run_status_store,
    get_step_result_store,
    get_upload_dir,
)
from patent_ai.api.main import create_app
from patent_ai.core.cases.results import InMemoryOAResultStore
from patent_ai.core.cases.run_inputs import RunInputSource
from patent_ai.core.cases.step_results import InMemoryStepResultStore
from patent_ai.core.cases.store import InMemoryCaseAppStore, InMemoryRunStore
from patent_ai.core.llm.limits import RunContext
from patent_ai.core.runs.cancel import CancelRegistry
from patent_ai.core.runs.run_case_executor import RunCaseExecutor
from tests.api.repo_fake import FakeRepoUnit
from tests.core.run_case_fakes import CHECKED_ON, real_config

PDF = b"%PDF-1.7\nA"


class FakeUnit:
    """get_case_unit 대신: 메모리 사건 저장소 + 커밋 흉내."""

    def __init__(self, store) -> None:
        self.store = store

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


class NewCase:
    """같은 OA·같은 사건이 없는 새 사건 (지휘의 CaseStore)."""

    def find_oa(self, application_number, dispatch_number):
        return None

    def find_case(self, application_number):
        return None


class RunCaseApp:
    """앱 하나와 그 앱이 같이 쓰는 메모리 저장소들.

    make_inputs: 메모리 사건 저장소를 받아 실행 입력(RunInputSource)을 만든다.
    make_ctx: 실행 이름을 받아 모델 호출 맥락을 만든다 (실행마다 새로).
    launch_enabled를 끄면 실행이 queued로 남는다.
    """

    def __init__(
        self,
        tmp_path: Path,
        *,
        make_inputs: Callable[[InMemoryCaseAppStore], RunInputSource],
        make_ctx: Callable[[str], RunContext],
    ) -> None:
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
            inputs=make_inputs(self.cases),
            cases=NewCase(),
            config_path=real_config(tmp_path),
            make_ctx=make_ctx,
            today=lambda: CHECKED_ON,
        )
        unit = FakeUnit(self.cases)
        app = create_app(startup_store=self.runs)
        app.dependency_overrides.update(
            {
                get_case_unit: lambda: unit,
                get_case_repository_unit: FakeRepoUnit,
                get_upload_dir: lambda: tmp_path,
                get_run_status_store: lambda: self.runs,
                get_cancel_registry: lambda: self.registry,
                get_oa_result_store: lambda: self.oa_results,
                get_step_result_store: lambda: self.steps,
                get_run_executor: lambda: self.executor,
                get_run_launcher: lambda: self._launch,
            }
        )
        self.client = TestClient(app, raise_server_exceptions=False)

    def _launch(self, run_id: str, oa_id: str) -> None:
        # 그 자리에서 바로 돈다 (진짜 앱은 백그라운드 스레드)
        if self.launch_enabled:
            self.executor.execute(run_id, oa_id)

    def upload(self, pdf: bytes = PDF) -> dict:
        """사건 하나를 올린다. 실패하면 그 자리에서 멈춘다 (뒤 단언이 엉뚱하게 깨지지 않게)."""
        res = self.client.post("/cases", files={"file": ("oa.pdf", pdf, "application/pdf")})
        assert res.status_code == 200, res.text
        return res.json()

    def get(self, oa_id: str, name: str):
        return self.client.get(f"/oas/{oa_id}/{name}")
