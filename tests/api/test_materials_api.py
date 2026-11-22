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
from patent_ai.core.cases.case_fill import InMemoryCaseFill
from patent_ai.core.cases.materials import InMemoryCaseMaterialsStore
from patent_ai.core.cases.store import InMemoryCaseAppStore, InMemoryRunStore
from patent_ai.core.schemas.case_materials import CaseMaterials
from patent_ai.core.schemas.common import Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.oa_result import OAResult

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


# --- 실행 뒤 사건 자료 (#261) -----------------------------------------------------


def _oa_result(oa_id: str, read_number: bool = True) -> OAResult:
    oa = OAResult.model_validate_json((FIXTURE / "oa_result.json").read_text("utf-8"))
    oa = oa.model_copy(update={"oa_id": oa_id})
    if not read_number:
        unread = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
        app = oa.application_number.model_copy(update={"value": None, "status": unread})
        oa = oa.model_copy(update={"application_number": app})
    return oa


@pytest.fixture
def filled(tmp_path):
    """env와 같은 앱에 사건 채우기(실행기가 F1 뒤 부르는 것)를 같은 메모리 저장소로 건다."""
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
    return client, InMemoryCaseFill(cases, materials), created


def test_결과_전_404는_출원번호_확인_전이라는_이유를_준다(env):
    client, _, created = env
    res = client.get(f"/cases/{created['case_id']}/materials")
    assert res.json()["code"] == "result_not_ready"
    assert "출원번호 확인 전" in res.json()["message"]


def test_실행_뒤_번호를_읽었으면_사건_이름과_사건_자료가_온다(filled):
    client, fill, created = filled
    oa_id, run_id = created["oa_id"], created["run_id"]
    fill.fill_after_f1(oa_id, run_id, _oa_result(oa_id), None)

    assert client.get(f"/cases/{created['case_id']}").json()["case_name"] == "1020990000001"
    res = client.get(f"/cases/{created['case_id']}/materials")
    assert res.status_code == 200
    assert res.json()["run_id"] == run_id
    docs = res.json()["result"]["documents"]
    oa_doc = client.get(f"/oas/{oa_id}").json()["document_id"]
    assert [d["document_id"] for d in docs] == [oa_doc]


def test_실행_뒤_출원번호를_못_읽었으면_이유가_있는_404다(filled):
    client, fill, created = filled
    oa_id, run_id = created["oa_id"], created["run_id"]
    fill.fill_after_f1(oa_id, run_id, _oa_result(oa_id, read_number=False), None)

    assert client.get(f"/cases/{created['case_id']}").json()["case_name"] == "출원번호 확인 전"
    res = client.get(f"/cases/{created['case_id']}/materials")
    assert res.status_code == 404 and res.json()["code"] == "result_not_ready"
    assert "출원번호 확인 전" in res.json()["message"]
