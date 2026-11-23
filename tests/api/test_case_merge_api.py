"""같은 출원번호 사건에 올린 OA 합치기의 API 모습 (이슈 #272).

확인: uv run pytest tests/api -k case_merge. 합치는 규칙은 tests/core/cases/test_case_fill.py.
네트워크·DB 없음 (메모리 저장소, 실행기 대신 사건 채우기를 바로 부름).
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from patent_ai.api.deps import (
    get_case_materials_store,
    get_case_repository_unit,
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
from patent_ai.core.schemas.oa_result import OAResult
from tests.api.repo_fake import FakeRepoUnit
from tests.core.run_case_app import FakeUnit

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "case_missing_citation"
APP = "1020990000001"
DISP2 = "952099000000002"


def _oa(oa_id: str, dispatch: str | None = None) -> OAResult:
    oa = OAResult.model_validate_json((FIXTURE / "oa_result.json").read_text("utf-8"))
    oa = oa.model_copy(update={"oa_id": oa_id})
    if dispatch is not None:
        disp = oa.dispatch_number.model_copy(update={"value": dispatch})
        oa = oa.model_copy(update={"dispatch_number": disp})
    return oa


def _pdf(body: bytes):
    return {"file": ("oa.pdf", b"%PDF-1.7\n" + body, "application/pdf")}


@pytest.fixture
def merged(tmp_path):
    """1차 OA로 사건을 만든 뒤, 같은 출원의 2차 OA를 새 사건으로 올려 실행이 끝난 상태."""
    runs = InMemoryRunStore()
    cases = InMemoryCaseAppStore(runs=runs)
    materials = InMemoryCaseMaterialsStore()
    results: dict[str, OAResult] = {}
    fill = InMemoryCaseFill(cases, materials, results.get)
    unit = FakeUnit(cases)
    app = create_app(startup_store=runs)
    app.dependency_overrides[get_case_unit] = lambda: unit
    app.dependency_overrides[get_case_repository_unit] = FakeRepoUnit
    app.dependency_overrides[get_upload_dir] = lambda: tmp_path
    app.dependency_overrides[get_run_status_store] = lambda: runs
    app.dependency_overrides[get_case_materials_store] = lambda: materials
    app.dependency_overrides[get_run_executor] = lambda: None
    app.dependency_overrides[get_run_launcher] = lambda: lambda run_id, oa_id: None
    client = TestClient(app, raise_server_exceptions=False)

    first = client.post("/cases", files=_pdf(b"1")).json()
    results[first["oa_id"]] = _oa(first["oa_id"])
    fill.fill_after_f1(first["oa_id"], first["run_id"], results[first["oa_id"]], None)
    second = client.post("/cases", files=_pdf(b"2")).json()
    fill.fill_after_f1(second["oa_id"], second["run_id"], _oa(second["oa_id"], DISP2), None)
    return client, first, second


def test_사건_목록에는_기존_사건_한_줄만_남고_최근_OA가_새_OA다(merged):
    client, first, second = merged
    rows = client.get("/cases").json()
    assert [r["case_id"] for r in rows] == [first["case_id"]]
    assert rows[0]["latest_oa"]["oa_id"] == second["oa_id"]


def test_기존_사건에_두_OA가_있고_새_OA는_그_사건을_가리킨다(merged):
    client, first, second = merged
    case = client.get(f"/cases/{first['case_id']}").json()
    assert (case["case_name"], case["merged_into_case_id"]) == (APP, None)
    assert [o["oa_id"] for o in case["oas"]] == [first["oa_id"], second["oa_id"]]
    oa = client.get(f"/oas/{second['oa_id']}").json()
    assert (oa["case_id"], oa["dispatch_number"]) == (first["case_id"], DISP2)


def test_임시_사건은_지우지_않고_합친_사건_id를_알려_준다(merged):
    client, first, second = merged
    res = client.get(f"/cases/{second['case_id']}")
    assert res.status_code == 200
    assert res.json()["merged_into_case_id"] == first["case_id"]
    assert res.json()["oas"] == []
    # 사건 자료는 합친 사건에 있다: 이유 없는 404가 아니라 그 사건 id를 알려 준다
    res = client.get(f"/cases/{second['case_id']}/materials")
    assert res.status_code == 404 and first["case_id"] in res.json()["message"]
    # 옛 링크로 임시 사건에 빠진 자료를 올려도 합친 사건 id를 알려 준다
    res = client.post(
        f"/cases/{second['case_id']}/documents", files=_pdf(b"x"), data={"what": "D1"}
    )
    assert res.status_code == 404 and first["case_id"] in res.json()["message"]


def test_실행은_최종_case_id를_돌려준다(merged):
    client, first, second = merged
    assert client.get(f"/runs/{second['run_id']}").json()["case_id"] == first["case_id"]
    assert client.get(f"/runs/{first['run_id']}").json()["case_id"] == first["case_id"]


def test_기존_사건_자료에_새_OA_원문까지_들어간다(merged):
    client, first, second = merged
    body = client.get(f"/cases/{first['case_id']}/materials").json()
    assert body["run_id"] == second["run_id"]
    docs = [client.get(f"/oas/{x['oa_id']}").json()["document_id"] for x in (first, second)]
    assert [d["document_id"] for d in body["result"]["documents"]] == docs


def test_합친_임시_사건에_다음_OA를_올리면_합친_사건에_붙는다(merged):
    # 옛 화면 링크로 임시 사건에 올려도 목록에서 숨은 사건에 OA가 묻히지 않게
    client, first, second = merged
    third = client.post(f"/cases/{second['case_id']}/oas", files=_pdf(b"3")).json()
    assert client.get(f"/oas/{third['oa_id']}").json()["case_id"] == first["case_id"]
    oas = client.get(f"/cases/{first['case_id']}").json()["oas"]
    assert [o["oa_id"] for o in oas][-1] == third["oa_id"]
