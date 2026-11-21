"""사건 자료 결과 받기 API 테스트 (#57 T6): TestClient + 메모리 fake. DB 없음."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from patent_ai.api.deps import (
    get_case_materials_store,
    get_case_unit,
    get_run_executor,
    get_run_launcher,
    get_run_status_store,
    get_upload_dir,
)
from patent_ai.api.main import create_app
from patent_ai.core.cases.materials import InMemoryCaseMaterialsStore
from patent_ai.core.cases.store import InMemoryCaseAppStore, InMemoryRunStore
from patent_ai.core.schemas.case_materials import CaseMaterials

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "case_missing_citation"


class FakeUnit:
    def __init__(self, store):
        self.store = store

    def commit(self):
        pass

    def rollback(self):
        pass


@pytest.fixture
def env(tmp_path):
    runs = InMemoryRunStore()
    cases = InMemoryCaseAppStore(runs=runs)
    materials = InMemoryCaseMaterialsStore()
    unit = FakeUnit(cases)
    app = create_app(startup_store=runs)
    app.dependency_overrides[get_case_unit] = lambda: unit
    app.dependency_overrides[get_upload_dir] = lambda: tmp_path
    app.dependency_overrides[get_run_status_store] = lambda: runs
    app.dependency_overrides[get_case_materials_store] = lambda: materials
    app.dependency_overrides[get_run_executor] = lambda: None
    app.dependency_overrides[get_run_launcher] = lambda: lambda run_id, oa_id: None
    client = TestClient(app, raise_server_exceptions=False)
    created = client.post(
        "/cases", files={"file": ("oa.pdf", b"%PDF-1.7\nA", "application/pdf")}
    ).json()
    return client, materials, created


def _fixture() -> CaseMaterials:
    return CaseMaterials.model_validate_json((FIXTURE / "case_materials.json").read_text("utf-8"))


def test_없는_사건은_404_case_not_found(env):
    client, _, _ = env
    res = client.get("/cases/c_없음/materials")
    assert res.status_code == 404
    assert set(res.json()) == {"code", "message"} and res.json()["code"] == "case_not_found"


def test_결과_전에는_404_result_not_ready(env):
    client, _, created = env
    res = client.get(f"/cases/{created['case_id']}/materials")
    assert res.status_code == 404
    assert set(res.json()) == {"code", "message"} and res.json()["code"] == "result_not_ready"


def test_있으면_결과_스키마_그대로_준다(env):
    client, materials, created = env
    materials.put(created["case_id"], created["run_id"], _fixture())
    res = client.get(f"/cases/{created['case_id']}/materials")
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"case_id", "run_id", "result"}
    assert body["case_id"] == created["case_id"] and body["run_id"] == created["run_id"]
    assert body["result"] == _fixture().model_dump(mode="json")


def test_run_id가_비어_있어도_준다(env):
    # 자료만 더하고 실행 없이 저장된 줄은 run_id가 null이다
    client, materials, created = env
    materials.put(created["case_id"], None, _fixture())
    body = client.get(f"/cases/{created['case_id']}/materials").json()
    assert body["run_id"] is None
