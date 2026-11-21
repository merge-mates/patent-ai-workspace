"""OA 엔드포인트 API 테스트 (#56 T3): TestClient + 메모리 fake + 임시 폴더. DB 없음."""

import hashlib
import itertools
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from patent_ai.api.deps import (
    get_case_unit,
    get_run_launcher,
    get_run_status_store,
    get_upload_dir,
)
from patent_ai.api.main import create_app
from patent_ai.core.cases.store import InMemoryCaseAppStore, InMemoryRunStore

PDF_A = b"%PDF-1.7\nA"
PDF_B = b"%PDF-1.7\nB"


class FakeUnit:
    def __init__(self, store):
        self.store = store

    fail_commit = False

    def commit(self):
        if self.fail_commit:
            raise RuntimeError("DB 저장 실패 흉내")

    def rollback(self):
        pass


@pytest.fixture
def env(tmp_path):
    # 시계를 1초씩 늘려 "가장 최근"이 늘 같은 답이 되게 한다
    ticks = itertools.count()
    t0 = datetime(2099, 1, 1, tzinfo=UTC)

    def clock():
        return t0 + timedelta(seconds=next(ticks))

    runs = InMemoryRunStore(clock=clock)
    store = InMemoryCaseAppStore(runs=runs, clock=clock)
    unit = FakeUnit(store)
    app = create_app()
    app.dependency_overrides[get_case_unit] = lambda: unit
    app.dependency_overrides[get_upload_dir] = lambda: tmp_path
    # 실행기를 안 돌리는 launcher: 실행이 queued로 남아 업로드 동작만 본다 (#57 이후 기본은 실행기)
    app.dependency_overrides[get_run_status_store] = lambda: runs
    app.dependency_overrides[get_run_launcher] = lambda: lambda run_id, oa_id: None
    return TestClient(app, raise_server_exceptions=False), runs, tmp_path, unit


def _pdf(data):
    return {"file": ("oa.pdf", data, "application/pdf")}


def test_다음_OA를_올리면_사건_보기에_OA가_2개(env):
    client, _, root, _ = env
    first = client.post("/cases", files=_pdf(PDF_A)).json()
    res = client.post(f"/cases/{first['case_id']}/oas", files=_pdf(PDF_B))
    assert res.status_code == 200
    second = res.json()
    assert set(second) == {"oa_id", "run_id"}
    detail = client.get(f"/cases/{first['case_id']}").json()
    assert [o["oa_id"] for o in detail["oas"]] == [first["oa_id"], second["oa_id"]]
    assert len(list((root / first["case_id"]).glob("*.pdf"))) == 2  # 파일도 같은 사건 폴더에


def test_OA_보기는_가장_최근_실행을_준다(env):
    client, runs, _, unit = env
    created = client.post("/cases", files=_pdf(PDF_A)).json()
    newer = runs.create_queued(created["oa_id"])  # 같은 OA에 실행이 하나 더
    body = client.get(f"/oas/{created['oa_id']}").json()
    # 올린 파일의 sha256으로 저장소에서 찾은 문서 ID와 같아야 한다
    doc = unit.store.find_document_by_sha256(hashlib.sha256(PDF_A).hexdigest())
    assert body == {
        "oa_id": created["oa_id"],
        "case_id": created["case_id"],
        "case_name": "출원번호 확인 전",
        "document_id": doc.document_id,
        "latest_run": {"run_id": newer.id, "state": "queued", "current_step": None},
        "dispatch_number": None,
    }


def test_같은_사건에_같은_파일은_409(env):
    client, _, root, _ = env
    first = client.post("/cases", files=_pdf(PDF_A)).json()
    res = client.post(f"/cases/{first['case_id']}/oas", files=_pdf(PDF_A))
    assert res.status_code == 409
    body = res.json()
    assert body["code"] == "document_already_exists"
    assert body["case_id"] == first["case_id"] and body["oa_id"] == first["oa_id"]
    assert len(client.get(f"/cases/{first['case_id']}").json()["oas"]) == 1
    assert len([p for p in root.rglob("*") if p.is_file()]) == 1


def test_다른_사건에_있는_파일은_다음_OA로_올릴_수_있다(env):
    client, _, _, _ = env
    a = client.post("/cases", files=_pdf(PDF_A)).json()
    b = client.post("/cases", files=_pdf(PDF_B)).json()
    res = client.post(f"/cases/{b['case_id']}/oas", files=_pdf(PDF_A))
    assert res.status_code == 200
    assert a["case_id"] != b["case_id"]


def test_없는_OA와_없는_사건은_404(env):
    client, _, _, _ = env
    res = client.get("/oas/oa_없음")
    assert res.status_code == 404 and res.json()["code"] == "oa_not_found"
    res = client.post("/cases/c_없음/oas", files=_pdf(PDF_A))
    assert res.status_code == 404 and res.json()["code"] == "case_not_found"


def test_다음_OA도_빈_파일과_PDF_아님은_422(env):
    client, _, _, _ = env
    case_id = client.post("/cases", files=_pdf(PDF_A)).json()["case_id"]
    assert client.post(f"/cases/{case_id}/oas", files=_pdf(b"")).json()["code"] == "empty_file"
    assert client.post(f"/cases/{case_id}/oas", files=_pdf(b"x")).json()["code"] == "not_pdf"


def test_다른_사건에_먼저_올린_파일을_다음_OA로_올린_뒤_다시_올리면_409에_기존_oa_id(env):
    client, _, _, _ = env
    client.post("/cases", files=_pdf(PDF_B))  # 사건 X (A는 아직 없음)
    x = client.post("/cases", files=_pdf(PDF_A)).json()  # 사건 X2에 A
    y = client.post("/cases", files=_pdf(PDF_B + b"y")).json()  # 사건 Y
    ok = client.post(f"/cases/{y['case_id']}/oas", files=_pdf(PDF_A))
    assert ok.status_code == 200
    res = client.post(f"/cases/{y['case_id']}/oas", files=_pdf(PDF_A))
    assert res.status_code == 409
    body = res.json()
    assert body["case_id"] == y["case_id"]
    assert body["oa_id"] == ok.json()["oa_id"]  # 사건 X의 oa가 아니라 Y 안의 OA
    assert body["oa_id"] != x["oa_id"]


def test_다음_OA_DB_저장이_실패하면_500이고_파일이_안_남는다(env):
    client, _, root, unit = env
    case_id = client.post("/cases", files=_pdf(PDF_A)).json()["case_id"]
    before = sorted(p for p in root.rglob("*") if p.is_file())
    unit.fail_commit = True
    res = client.post(f"/cases/{case_id}/oas", files=_pdf(PDF_B))
    assert res.status_code == 500 and res.json()["code"] == "upload_failed"
    assert sorted(p for p in root.rglob("*") if p.is_file()) == before
