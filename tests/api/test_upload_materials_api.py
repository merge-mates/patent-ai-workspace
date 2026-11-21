"""빠진 자료 올리기·사건 보기 API 테스트 (#16 T7): TestClient + 메모리 fake + 임시 폴더. DB 없음.

사건은 메모리 사건 저장소(#56)에 만들고, 묶기 결과는 메모리 사건 저장소(#16)에 같은 사건 ID로
넣는다. 번호는 모두 지어낸 것 (2099년 값).
"""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from patent_ai.api.deps import get_case_repository_unit, get_case_unit, get_upload_dir
from patent_ai.api.main import create_app
from patent_ai.core.cases.store import InMemoryCaseAppStore, NewDocument
from patent_ai.core.f1_oa_reader.case_repository import InMemoryCaseRepository
from patent_ai.core.schemas.case_materials import LookupResult
from tests.api.repo_fake import FakeRepoUnit
from tests.core.f1.test_case_repository import CASE_ID, _record

PDF = b"%PDF-1.7\nD1"
PDF_B = b"%PDF-1.7\nD2"


class FakeUnit:
    def __init__(self, store):
        self.store = store

    def commit(self):
        pass

    def rollback(self):
        pass


class SameOARepository(InMemoryCaseRepository):
    """Postgres에서는 두 저장소가 같은 oas 표를 쓴다. 메모리에서는 OA ID를 사건 저장소 것으로."""

    def __init__(self, oa_ids):
        super().__init__()
        self._oa_ids = oa_ids

    def oa_versions(self, case_id):
        rows = super().oa_versions(case_id)
        # 앞에서부터 사건 저장소 OA ID로 바꾸고, 남는 OA 줄은 그대로 둔다
        ids = [*self._oa_ids, *(r.oa_id for r in rows[len(self._oa_ids) :])]
        return [replace(r, oa_id=i) for r, i in zip(rows, ids, strict=True)]


def _app(tmp_path, repo_unit, store):
    app = create_app()
    app.dependency_overrides[get_case_unit] = lambda: FakeUnit(store)
    app.dependency_overrides[get_upload_dir] = lambda: tmp_path
    app.dependency_overrides[get_case_repository_unit] = lambda: repo_unit
    return TestClient(app, raise_server_exceptions=False)


def _new_case(store):
    doc = NewDocument(path="x.pdf", sha256="sha-oa", received_at=datetime(2099, 1, 1, tzinfo=UTC))
    return store.create_case(doc, case_id=CASE_ID)


@pytest.fixture
def env(tmp_path):
    store = InMemoryCaseAppStore()
    created = _new_case(store)
    repo = SameOARepository([created.oa_id])
    repo.save_case(_record())
    unit = FakeRepoUnit(repo)
    return _app(tmp_path, unit, store), unit, tmp_path


def _upload(client, what, data=PDF, case_id=CASE_ID):
    return client.post(
        f"/cases/{case_id}/documents",
        files={"file": ("d.pdf", data, "application/pdf")},
        data={"what": what},
    )


def _pdfs(root):
    return [p for p in root.rglob("*") if p.is_file()]


def test_materials_api_올리고_다시_열면_자료와_결과가_그대로(env):
    client, unit, root = env
    before = unit.repo.load_case_materials(CASE_ID)
    what = before.missing[0].what
    res = _upload(client, what)
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"case_id", "document_id", "result"}
    # 다시 열면(저장소에서 다시 읽으면) 응답과 같다
    again = unit.repo.load_case_materials(CASE_ID)
    assert body["result"] == again.model_dump(mode="json")
    assert body["document_id"] == again.documents[-1].document_id
    assert unit.commits == 1
    # 원본 파일은 사건 폴더에 하나
    (f,) = _pdfs(root)
    assert f.parent == root / CASE_ID and f.read_bytes() == PDF


def test_materials_api_빠진_자료가_검토할_사항에_뜨고_올리면_빠진다(env):
    client, unit, _ = env
    before = unit.repo.load_case_materials(CASE_ID)
    assert before.missing and before.review_items_count >= len(before.missing)
    what = before.missing[0].what
    after = _upload(client, what).json()["result"]
    assert what not in {m["what"] for m in after["missing"]}
    assert what not in {h["waiting_for"] for h in after["held_tasks"]}
    assert after["review_items_count"] == before.review_items_count - 1
    # 다른 빠진 자료와 그 보류는 그대로 남는다
    assert [m["what"] for m in after["missing"]] == [m.what for m in before.missing[1:]]


def test_materials_api_같은_파일을_다시_올리면_409(env):
    client, unit, root = env
    missing = unit.repo.load_case_materials(CASE_ID).missing
    assert _upload(client, missing[0].what).status_code == 200
    res = _upload(client, missing[1].what)  # 같은 파일을 다른 빠진 자료에
    assert res.status_code == 409
    assert res.json() == {
        "code": "document_already_exists",
        "message": "이미 올린 파일입니다",
        "case_id": CASE_ID,
    }
    assert len(_pdfs(root)) == 1  # 임시 파일은 남지 않는다
    assert missing[1].what in {m.what for m in unit.repo.load_case_materials(CASE_ID).missing}


def test_materials_api_없는_사건은_404_case_not_found(env):
    client, _, root = env
    res = _upload(client, "x", case_id="c_없음")
    assert res.status_code == 404 and res.json()["code"] == "case_not_found"
    assert not _pdfs(root)


def test_materials_api_묶기_결과_전이면_404_result_not_ready(tmp_path):
    store = InMemoryCaseAppStore()
    _new_case(store)
    client = _app(tmp_path, FakeRepoUnit(), store)
    res = _upload(client, "x")
    assert res.status_code == 404 and res.json()["code"] == "result_not_ready"


def test_materials_api_빠진_자료가_아니면_422이고_파일을_안_씀(env):
    client, unit, root = env
    before = unit.repo.load_case_materials(CASE_ID)
    res = _upload(client, "D9 없는 문헌 본문")
    assert res.status_code == 422 and res.json()["code"] == "missing_not_found"
    assert not _pdfs(root)
    assert unit.repo.load_case_materials(CASE_ID) == before


def test_materials_api_PDF가_아니면_422(env):
    client, unit, root = env
    what = unit.repo.load_case_materials(CASE_ID).missing[0].what
    res = _upload(client, what, data=b"hello")
    assert res.status_code == 422 and res.json()["code"] == "not_pdf"
    assert not _pdfs(root)


def test_materials_api_DB_저장이_실패하면_500이고_파일이_안_남는다(env):
    client, unit, root = env
    unit.fail_commit = True
    what = unit.repo.load_case_materials(CASE_ID).missing[0].what
    res = _upload(client, what)
    assert res.status_code == 500 and res.json()["code"] == "upload_failed"
    assert not _pdfs(root)


def test_materials_api_사건_보기에_이력_청구항_판_OA별_심사_대상_판(env):
    client, _, _ = env
    body = client.get(f"/cases/{CASE_ID}").json()
    assert [(e["kind"], e["doc_number"], e["seq"]) for e in body["events"][:3]] == [
        ("oa", "952099000000001", 1),
        ("amendment", "112099000000112", 2),
        ("oa", "952099000000002", 3),
    ]
    # 판이 섞이지 않는다: 출원 때 판 0, 보정서 판 1. 등록공보 판은 OA 당시 판이 아니라 빠진다
    assert [(v["version"], v["source_kind"]) for v in body["claim_versions"]] == [
        (0, "application"),
        (1, "amendment"),
    ]
    (oa,) = body["oas"]
    assert oa["examined_claim_version"]["value"] == "as_filed"
    assert oa["examined_claim_version"]["status"]["value"] == "confirmed"


def test_materials_api_직접_확인할_자료는_422_upload_not_asked(env):
    client, unit, root = env
    saved = unit.repo.load_case_materials(CASE_ID)
    first = saved.missing[0].model_copy(
        update={"ask_upload": False, "lookup_result": LookupResult.UNSUPPORTED_COUNTRY}
    )
    # 저장소 값을 바꿔 지원 안 하는 나라 자료를 흉내 낸다
    rows = unit.repo._cases[CASE_ID]
    body = saved.model_copy(update={"missing": [first, *saved.missing[1:]]}).model_dump(mode="json")
    unit.repo._cases[CASE_ID] = replace(rows, materials_body=body)
    res = _upload(client, first.what)
    assert res.status_code == 422 and res.json()["code"] == "upload_not_asked"
    assert not _pdfs(root)


def test_materials_api_빈_파일은_422_empty_file(env):
    client, unit, root = env
    what = unit.repo.load_case_materials(CASE_ID).missing[0].what
    res = _upload(client, what, data=b"")
    assert res.status_code == 422 and res.json()["code"] == "empty_file"
    assert not _pdfs(root)
