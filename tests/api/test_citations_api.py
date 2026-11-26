"""GET /citations/{doc_id}: 인용문헌 원문 전체 (색인 조각을 문헌 순서로)."""

from fastapi.testclient import TestClient

from patent_ai.api.citations import get_cite_index_version, get_cite_repo
from patent_ai.api.main import create_app
from patent_ai.retrieval.repository import InMemoryChunkRepository
from patent_ai.retrieval.schemas import Chunk, Edition, Location


def _chunk(cid, kind, loc_kind, label, text, start=None):
    return Chunk(
        chunk_id=f"idx:KR1A:{cid}", index_version="idx", doc_id="KR1A", chunk_kind=kind,
        location=Location(kind=loc_kind, start=start, end=start, label=label),
        edition=Edition(status="not_applicable"), text=text,
    )  # fmt: skip


def _client():
    repo = InMemoryChunkRepository(
        {
            "cite": [
                _chunk("p0001", "body", "paragraph", "[0001]", "첫 문단", start=1),
                _chunk("abs", "abstract", "abstract", "요약", "요약 글"),
            ]
        }
    )
    app = create_app()
    app.dependency_overrides[get_cite_repo] = lambda: repo
    app.dependency_overrides[get_cite_index_version] = lambda: "idx"
    return TestClient(app)


def test_인용문헌_원문을_문헌_순서로_준다():
    body = _client().get("/citations/KR1A").json()
    assert body["doc_id"] == "KR1A"
    assert [(p["label"], p["text"]) for p in body["parts"]] == [
        ("요약", "요약 글"),
        ("[0001]", "첫 문단"),
    ]


def test_색인에_없는_문헌은_404():
    res = _client().get("/citations/KR9A")
    assert res.status_code == 404 and res.json()["code"] == "citation_not_found"


def test_인용문헌_원본_PDF를_사건_폴더에서_준다(tmp_path):
    from patent_ai.api.citations import get_cite_root

    folder = tmp_path / "1020990000001"
    folder.mkdir()
    (folder / "KR1A.pdf").write_bytes(b"%PDF-1.4 test")
    app = create_app()
    app.dependency_overrides[get_cite_root] = lambda: tmp_path
    client = TestClient(app)
    r = client.get("/citations/KR1A/file", params={"application_number": "1020990000001"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content == b"%PDF-1.4 test"
    miss = client.get("/citations/KR9A/file", params={"application_number": "1020990000001"})
    assert miss.status_code == 404 and miss.json()["code"] == "citation_file_not_found"
