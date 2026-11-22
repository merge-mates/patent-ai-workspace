"""GET /documents/{id} API 테스트 (#262): 올린 통지서의 쪽 글자. TestClient + 메모리 fake, DB 없음.

PDF는 테스트 안에서 지어낸 글자로 만든다 (실제 통지서 아님).
"""

import io

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

from patent_ai.api.deps import (
    get_case_repository_unit,
    get_case_unit,
    get_run_launcher,
    get_run_status_store,
    get_upload_dir,
)
from patent_ai.api.main import create_app
from patent_ai.core.cases.store import InMemoryCaseAppStore, InMemoryRunStore
from tests.api.repo_fake import FakeRepoUnit


class FakeUnit:
    def __init__(self, store):
        self.store = store

    def commit(self):
        pass

    def rollback(self):
        pass


def _pdf(texts: list[str]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for t in texts:
        c.drawString(72, 720, t)
        c.showPage()
    c.save()
    return buf.getvalue()


@pytest.fixture
def client(tmp_path):
    runs = InMemoryRunStore()
    unit = FakeUnit(InMemoryCaseAppStore(runs=runs))
    app = create_app()
    app.dependency_overrides[get_case_unit] = lambda: unit
    app.dependency_overrides[get_upload_dir] = lambda: tmp_path
    app.dependency_overrides[get_case_repository_unit] = lambda: FakeRepoUnit()
    app.dependency_overrides[get_run_status_store] = lambda: runs
    # 실행기를 안 돌린다: 올리기와 원문 읽기만 본다
    app.dependency_overrides[get_run_launcher] = lambda: lambda run_id, oa_id: None
    return TestClient(app, raise_server_exceptions=False)


def _upload(client, data: bytes) -> str:
    """사건을 올리고 그 OA의 문서 ID를 돌려준다 (화면처럼 GET /oas/{id}의 document_id)."""
    r = client.post("/cases", files={"file": ("oa.pdf", data, "application/pdf")})
    assert r.status_code == 200, r.text
    oa = client.get(f"/oas/{r.json()['oa_id']}").json()
    return oa["document_id"]


def test_올린_통지서의_쪽_글자를_돌려준다(client):
    doc_id = _upload(client, _pdf(["Notice page one", "Claim 1 is rejected."]))
    r = client.get(f"/documents/{doc_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["document_id"] == doc_id
    assert [p["page"] for p in body["pages"]] == [1, 2]
    assert "Notice page one" in body["pages"][0]["text"]
    assert "Claim 1 is rejected." in body["pages"][1]["text"]
    assert body["status"]["value"] == "confirmed"
    # 화면 PageText 모양: 쪽마다 status·tables 칸이 있다
    assert set(body["pages"][0]) == {"page", "text", "status", "tables"}


def test_없는_문서는_404_document_not_found(client):
    r = client.get("/documents/doc_없음")
    assert r.status_code == 404
    assert r.json()["code"] == "document_not_found"


def test_원본_파일이_사라졌으면_200_확인되지_않음과_빈_쪽(client, tmp_path):
    doc_id = _upload(client, _pdf(["Notice page one"]))
    for f in tmp_path.rglob("*.pdf"):
        f.unlink()
    r = client.get(f"/documents/{doc_id}")
    # 요청은 맞다: HTTP 오류가 아니라 status로 알린다 (docs/api/README.md 1절)
    assert r.status_code == 200
    body = r.json()
    assert body["pages"] == []
    assert body["status"]["value"] == "unverified"
    assert body["status"]["reason"] == "lookup_failed"
