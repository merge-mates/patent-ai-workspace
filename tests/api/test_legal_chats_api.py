"""법률 질문 대화 API 테스트 (#29 task-3): 메모리 대화 저장소 + 메모리 법령 repo. DB 없음."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from patent_ai.api import deps
from patent_ai.api.deps import get_legal_chat_unit, get_legal_index, get_today
from patent_ai.api.main import create_app
from patent_ai.core.cases.store import CaseNotFoundError
from patent_ai.core.f2_legal_research import index as legal_index
from patent_ai.core.f2_legal_research.chat_store import ChatCorrupt, InMemoryLegalChatStore
from patent_ai.core.f2_legal_research.index import LegalIndex
from patent_ai.core.f2_legal_research.run import F2Settings
from patent_ai.core.f2_legal_research.tools import LawPool
from patent_ai.retrieval.contract import get_searcher
from patent_ai.retrieval.repository import InMemoryChunkRepository
from tests.core.f2 import fakes
from tests.core.f2.fakes import IV, NEW_DOC, SEARCH

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


class NoClose(InMemoryChunkRepository):
    def close(self):
        pass


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


def test_legal_chats_api_색인_판이_없으면_못_읽은_것으로_본다(monkeypatch, caplog):
    deps._cached_legal_index.cache_clear()
    monkeypatch.setattr(legal_index, "open_law_repo", lambda: NoClose({"law": []}))
    with caplog.at_level("WARNING"):
        assert get_legal_index() is None
    assert any("색인" in r.message for r in caplog.records)
    deps._cached_legal_index.cache_clear()


def test_legal_chats_api_색인_조각이_0개면_못_읽은_것으로_본다(monkeypatch, caplog):
    """색인 판은 있으나 조각이 비면(그 판의 조각 0개) 캐시하지 않고 못 읽은 것으로 본다."""

    class EmptyPool(InMemoryChunkRepository):
        def has_index_version(self, corpus, index_version):
            return True

        def close(self):
            pass

    deps._cached_legal_index.cache_clear()
    monkeypatch.setattr(legal_index, "open_law_repo", lambda: EmptyPool({"law": []}))
    with caplog.at_level("WARNING"):
        assert get_legal_index() is None
    assert any("0개" in str(r.exc_info[1]) for r in caplog.records if r.exc_info)
    deps._cached_legal_index.cache_clear()


def test_legal_chats_api_색인_캐시는_메모리_조각만_두고_세션을_닫는다(monkeypatch):
    calls = {"made": 0, "closed": 0}
    base = fakes.repo()

    class Tracked:
        def has_index_version(self, corpus, index_version):
            return base.has_index_version(corpus, index_version)

        def chunks(self, corpus, index_version, **kw):
            return base.chunks(corpus, index_version, **kw)

        def close(self):
            calls["closed"] += 1

    def make():
        calls["made"] += 1
        return Tracked()

    deps._cached_legal_index.cache_clear()
    monkeypatch.setattr(legal_index, "open_law_repo", make)
    monkeypatch.setattr(deps, "get_f2_settings", lambda: F2Settings(index_version=IV, **SEARCH))
    first = get_legal_index()
    assert first is not None
    assert calls == {"made": 1, "closed": 1}  # 읽은 뒤 닫았다
    first.searcher.search("특허법 제29조", "law", "bm25", 3)  # 원 repo(DB)를 다시 부르지 않는다
    assert get_legal_index() is first
    assert calls == {"made": 1, "closed": 1}
    deps._cached_legal_index.cache_clear()


def test_legal_chats_api_본문이_객체가_아니면_invalid_question(client):
    chat_id = _new_chat(client)
    res = client.post(f"/legal-chats/{chat_id}/messages", json=[1])
    assert res.status_code == 422
    assert res.json()["code"] == "invalid_question"


def test_legal_chats_api_요청_스키마가_openapi에_실린다(client):
    spec = client.get("/openapi.json").json()
    schema = spec["paths"]["/legal-chats/{chat_id}/messages"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    assert schema["title"] == "ChatAsk" and "text" in schema["properties"]
    assert "$ref" not in str(schema)  # 풀지 않은 참조가 남지 않는다


def test_legal_chats_api_없는_사건이면_404_case_not_found(client):
    class NoCase(InMemoryLegalChatStore):
        def create(self, case_id, now):
            raise CaseNotFoundError(case_id)

    unit = FakeUnit()
    unit.store = NoCase()
    client.app.dependency_overrides[get_legal_chat_unit] = lambda: unit
    res = client.post("/legal-chats", json={"case_id": "c_없음"})
    assert (res.status_code, res.json()["code"]) == (404, "case_not_found")


def test_legal_chats_api_저장된_대화를_못_읽으면_500_chat_corrupt(client):
    class Corrupt(InMemoryLegalChatStore):
        def get(self, chat_id):
            raise ChatCorrupt(chat_id)

    unit = FakeUnit()
    unit.store = Corrupt()
    client.app.dependency_overrides[get_legal_chat_unit] = lambda: unit
    got = client.get("/legal-chats/lc_1")
    asked = client.post("/legal-chats/lc_1/messages", json={"text": "특허법 제29조제2항"})
    for res in (got, asked):
        assert (res.status_code, res.json()["code"]) == (500, "chat_corrupt")


def test_legal_chats_api_DB_연결_실패는_못_읽은_것으로_본다(monkeypatch, caplog):
    def down():
        raise OperationalError("select 1", {}, Exception("연결 실패"))

    deps._cached_legal_index.cache_clear()
    monkeypatch.setattr(legal_index, "open_law_repo", down)
    with caplog.at_level("WARNING"):
        assert get_legal_index() is None
    assert any("색인" in r.message for r in caplog.records)
    deps._cached_legal_index.cache_clear()


def test_legal_chats_api_설정_오류는_색인_없음으로_넘기지_않는다(monkeypatch):
    bad = F2Settings(index_version=IV, **{**SEARCH, "bm25": {"없는키": 1}})
    deps._cached_legal_index.cache_clear()
    monkeypatch.setattr(
        legal_index, "open_law_repo", lambda: NoClose({"law": fakes.repo().chunks("law", IV)})
    )
    monkeypatch.setattr(deps, "get_f2_settings", lambda: bad)
    with pytest.raises(ValueError):
        get_legal_index()
    # 서버 시작(lifespan)에서도 터진다
    with pytest.raises(ValueError), TestClient(create_app(object())):
        pass
    deps._cached_legal_index.cache_clear()
