"""사건 엔드포인트 API 테스트 (#56 T2): TestClient + 메모리 fake + 임시 폴더. DB 없음."""

import pytest
from fastapi.testclient import TestClient

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

PDF = b"%PDF-1.7\nA"
PDF_B = b"%PDF-1.7\nB"


class FakeUnit:
    """메모리 저장소 + 커밋. fail_commit이면 DB 저장 실패를 흉내 낸다."""

    def __init__(self, store, fail_commit=False):
        self.store = store
        self.fail_commit = fail_commit

    def commit(self):
        if self.fail_commit:
            raise RuntimeError("DB 저장 실패 흉내")

    def rollback(self):
        pass


@pytest.fixture
def env(tmp_path):
    runs = InMemoryRunStore()
    store = InMemoryCaseAppStore(runs=runs)
    unit = FakeUnit(store)
    app = create_app()
    app.dependency_overrides[get_case_unit] = lambda: unit
    app.dependency_overrides[get_upload_dir] = lambda: tmp_path
    app.dependency_overrides[get_case_repository_unit] = lambda: FakeRepoUnit()
    # 실행기를 안 돌리는 launcher: 실행이 queued로 남아 업로드 동작만 본다 (#57 이후 기본은 실행기)
    app.dependency_overrides[get_run_status_store] = lambda: runs
    app.dependency_overrides[get_run_launcher] = lambda: lambda run_id, oa_id: None
    return TestClient(app, raise_server_exceptions=False), unit, tmp_path


def _post(client, data=PDF, name="oa.pdf", ctype="application/pdf"):
    return client.post("/cases", files={"file": (name, data, ctype)})


def test_올리면_파일이_upload_dir에_생기고_응답은_API_예시_모양(env):
    client, _, root = env
    res = _post(client)
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"case_id", "oa_id", "run_id"}
    files = [p for p in root.rglob("*") if p.is_file()]
    assert len(files) == 1  # 임시 파일은 남지 않는다
    assert files[0].parent == root / body["case_id"]
    assert files[0].suffix == ".pdf" and files[0].read_bytes() == PDF


def test_빈_목록(env):
    client, _, _ = env
    res = client.get("/cases")
    assert res.status_code == 200 and res.json() == []


def test_올린_뒤_목록과_상세(env):
    client, _, _ = env
    created = _post(client).json()
    row = client.get("/cases").json()[0]
    assert row["case_id"] == created["case_id"]
    assert row["case_name"] == "출원번호 확인 전"
    assert row["application_number"] is None
    assert row["latest_oa"] == {"oa_id": created["oa_id"], "notice_kind": None}
    assert row["rejection_kinds"] == []
    assert row["run_state"] == "queued"
    assert row["status"] == "unverified"
    assert row["review_items_count"] is None
    assert "updated_at" in row and "last_opened_at" not in row
    detail = client.get(f"/cases/{created['case_id']}").json()
    assert detail == {
        "case_id": created["case_id"],
        "case_name": "출원번호 확인 전",
        "oas": [{"oa_id": created["oa_id"], "notice_kind": None, "examined_claim_version": None}],
        # 묶기 결과(#16)가 저장되기 전이라 비어 있다
        "events": [],
        "claim_versions": [],
    }


def test_빈_파일은_422_empty_file(env):
    client, _, root = env
    res = _post(client, data=b"")
    assert res.status_code == 422 and res.json()["code"] == "empty_file"
    assert not list(root.rglob("*.pdf"))


def test_PDF가_아니면_422_not_pdf_content_type은_안_봄(env):
    client, _, _ = env
    res = _post(client, data=b"hello", ctype="application/pdf")
    assert res.status_code == 422 and res.json()["code"] == "not_pdf"
    # 거꾸로: content-type이 달라도 앞 5바이트가 %PDF- 면 통과
    assert _post(client, data=PDF_B, ctype="application/octet-stream").status_code == 200


def test_같은_파일_다시_올리면_409와_기존_ID(env):
    client, _, root = env
    first = _post(client).json()
    res = _post(client)
    assert res.status_code == 409
    body = res.json()
    assert body["code"] == "document_already_exists"
    assert body["case_id"] == first["case_id"] and body["oa_id"] == first["oa_id"]
    assert len(client.get("/cases").json()) == 1
    assert len([p for p in root.rglob("*") if p.is_file()]) == 1


def test_없는_사건은_404_case_not_found(env):
    client, _, _ = env
    res = client.get("/cases/c_없음")
    assert res.status_code == 404
    assert res.json()["code"] == "case_not_found"


def test_DB_저장이_실패하면_500_upload_failed이고_파일이_안_남는다(env):
    client, unit, root = env
    unit.fail_commit = True
    res = _post(client)
    assert res.status_code == 500 and res.json()["code"] == "upload_failed"
    assert not [p for p in root.rglob("*") if p.is_file()]


def test_라우터가_db_모듈을_직접_부르지_않는다():
    import pathlib

    api_dir = pathlib.Path(__file__).parents[2] / "src/patent_ai/api"
    bad = [p.name for p in api_dir.glob("*.py") if "patent_ai.db" in p.read_text()]
    assert bad == []
