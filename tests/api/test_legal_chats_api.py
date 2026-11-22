"""법률 질문 대화 API 테스트 (#29 task-3): 메모리 대화 저장소 + 메모리 법령 repo. DB 없음."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from patent_ai.api import deps
from patent_ai.api.deps import LegalIndex, get_legal_chat_unit, get_legal_index, get_today
from patent_ai.api.main import create_app
from patent_ai.core.f2_legal_research.chat_store import InMemoryLegalChatStore
from patent_ai.core.f2_legal_research.tools import LawPool
from patent_ai.retrieval.contract import get_searcher
from patent_ai.retrieval.repository import InMemoryChunkRepository
from tests.core.f2 import fakes
from tests.core.f2.fakes import IV, NEW_DOC

TODAY = date(2024, 1, 1)


class FakeUnit:
    def __init__(self):
        self.store = InMemoryLegalChatStore()

    def commit(self):
        pass

    def rollback(self):
        pass


def _index(repo) -> LegalIndex:
    pool = LawPool.load(repo, IV)
    searcher = get_searcher("bm25", repo, {"index_version": IV, "tokenizer": "char_bigram"})
    return LegalIndex(pool, searcher)


def _client(index) -> TestClient:
    unit = FakeUnit()
    app = create_app()
    app.dependency_overrides[get_legal_chat_unit] = lambda: unit
    app.dependency_overrides[get_legal_index] = lambda: index
    app.dependency_overrides[get_today] = lambda: TODAY
    return TestClient(app)


@pytest.fixture
def client():
    return _client(_index(fakes.repo()))


def _new_chat(client) -> str:
    res = client.post("/legal-chats", json={})
    assert res.status_code == 201
    return res.json()["chat_id"]


def test_legal_chats_api_만들기_묻기_보기(client):
    chat_id = _new_chat(client)
    res = client.post(f"/legal-chats/{chat_id}/messages", json={"text": "특허법 제29조제2항"})
    assert res.status_code == 200
    body = res.json()
    assert (body["chat_id"], body["no"], body["scope_changed"]) == (chat_id, 1, False)
    assert body["result"]["bundle_id"] == f"{chat_id}:1"

    view = client.get(f"/legal-chats/{chat_id}").json()
    assert view["chat_id"] == chat_id and view["case_id"] is None
    assert [t["no"] for t in view["turns"]] == [1]
    assert view["turns"][0]["result"] == body["result"]
    assert view["turns"][0]["question"]["text"] == "특허법 제29조제2항"
    assert view["prior_evidence"] == [f"{IV}:{NEW_DOC}:290002"]


def test_legal_chats_api_조문_번호_질문은_그_조문_근거를_낸다(client):
    chat_id = _new_chat(client)
    res = client.post(f"/legal-chats/{chat_id}/messages", json={"text": "특허법 제29조제2항"})
    result = res.json()["result"]
    assert result["status"]["value"] == "confirmed"
    ids = [s["evidence"]["chunk_id"] for c in result["claims"] for s in c["sources"]]
    assert ids == [f"{IV}:{NEW_DOC}:290002"]


def test_legal_chats_api_이어_묻기에서_시점을_바꾸면_scope_changed(client):
    chat_id = _new_chat(client)
    url = f"/legal-chats/{chat_id}/messages"
    client.post(url, json={"text": "특허법 제29조제2항"})
    same = client.post(url, json={"text": "제42조제4항"}).json()
    assert same["scope_changed"] is False and same["no"] == 2
    changed = client.post(url, json={"text": "특허법 제29조제2항", "as_of": "2016-01-01"}).json()
    assert changed["scope_changed"] is True
    assert changed["result"]["question"]["as_of"] == "2016-01-01"
    assert "구판" in changed["result"]["claims"][0]["sources"][0]["evidence"]["raw_text"]


def test_legal_chats_api_없는_대화는_404(client):
    res = client.get("/legal-chats/lc_없음")
    assert (res.status_code, res.json()["code"]) == (404, "chat_not_found")
    res = client.post("/legal-chats/lc_없음/messages", json={"text": "특허법 제29조제2항"})
    assert (res.status_code, res.json()["code"]) == (404, "chat_not_found")


@pytest.mark.parametrize("body", [{"text": "   "}, {"text": "질문", "as_of": "어제"}, {}])
def test_legal_chats_api_빈_글과_잘못된_요청은_422(client, body):
    chat_id = _new_chat(client)
    res = client.post(f"/legal-chats/{chat_id}/messages", json=body)
    assert res.status_code == 422
    assert res.json()["code"] == "invalid_question" and res.json()["message"]
    # 실패한 질문은 대화에 남지 않는다
    assert client.get(f"/legal-chats/{chat_id}").json()["turns"] == []


def test_legal_chats_api_색인을_못_읽으면_body_missing_묶음(caplog):
    client = _client(None)  # get_legal_index는 못 읽으면 None
    chat_id = _new_chat(client)
    with caplog.at_level("WARNING"):
        res = client.post(f"/legal-chats/{chat_id}/messages", json={"text": "특허법 제29조제2항"})
    result = res.json()["result"]
    assert res.status_code == 200
    assert result["claims"] == []
    assert result["status"]["value"] == "unverified"
    assert result["status"]["reason"] == "body_missing"
    assert any("색인" in r.message for r in caplog.records)


def test_legal_chats_api_색인_조각이_0개면_못_읽은_것으로_본다(monkeypatch, caplog):
    deps._load_legal_index.cache_clear()
    monkeypatch.setattr(deps, "make_law_repo", lambda: InMemoryChunkRepository({"law": []}))
    with caplog.at_level("WARNING"):
        assert get_legal_index() is None
    assert any("색인" in r.message for r in caplog.records)
    deps._load_legal_index.cache_clear()
