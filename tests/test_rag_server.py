import json
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from src.rag.server import handle_ask, make_server
from src.rag.settings import Settings

FULL = {"question": "q", "status": "answered", "answer": "원문 [E1]", "answer_display": "표시용 답변(특허법 제30조)",
        "cited": ["E1"], "cited_articles": ["특허법#제30조"],
        "citations": [{"article_id": "특허법#제30조", "label": "특허법 제30조"}],
        "evidence": [{"tag": "E1"}], "checks": {}, "retrieval": {"rerank_raw": "내부"},
        "generation": {"model": "m", "raw": "RAW"}, "seconds": {"retrieval": 3.0, "generation": 7.0}}


def ask_ok(message):
    ask_ok.seen.append(message)
    return FULL


ask_ok.seen = []


def body(**kw):
    return json.dumps(kw, ensure_ascii=False).encode("utf-8")


def test_handle_ask_returns_only_fields_the_screen_needs():
    ask_ok.seen.clear()
    status, out = handle_ask(body(message="  질문입니다  "), ask=ask_ok, max_message_len=1000)
    assert status == 200 and ask_ok.seen == ["질문입니다"]
    assert set(out) == {"status", "answer_display", "citations", "seconds"}  # 원문 응답·검색 내부·근거 본문은 보내지 않는다
    assert out["answer_display"] == "표시용 답변(특허법 제30조)" and out["citations"][0]["label"] == "특허법 제30조"


@pytest.mark.parametrize("raw", ["{깨진".encode(), b"[]", b'"x"', b"", b"null"])
def test_handle_ask_rejects_malformed_bodies(raw):
    assert handle_ask(raw, ask=ask_ok, max_message_len=1000)[0] == 400


@pytest.mark.parametrize("payload", [{}, {"message": ""}, {"message": "   "}, {"message": 5}, {"message": "가" * 1001}])
def test_handle_ask_rejects_bad_messages(payload):
    assert handle_ask(body(**payload), ask=ask_ok, max_message_len=1000)[0] == 400


def test_history_is_accepted_but_ignored_and_must_be_a_list():
    ask_ok.seen.clear()
    assert handle_ask(body(message="질문", history=[{"role": "user", "content": "앞 질문"}]), ask=ask_ok, max_message_len=1000)[0] == 200
    assert ask_ok.seen == ["질문"]  # 이전 대화는 검색·생성에 쓰이지 않는다(대화 기억은 다음 단계)
    assert handle_ask(body(message="질문", history="x"), ask=ask_ok, max_message_len=1000)[0] == 400


def test_failure_inside_ask_gives_generic_502_without_details(capsys):
    def boom(message):
        raise RuntimeError("생성 호출 실패: HTTP 401 sk-SECRET-KEY")

    status, out = handle_ask(body(message="질문"), ask=boom, max_message_len=1000)
    assert status == 502 and "SECRET" not in json.dumps(out, ensure_ascii=False)
    assert "SECRET" not in capsys.readouterr().err  # 로그에도 예외 종류만


@pytest.fixture
def server(tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>화면</html>", encoding="utf-8")
    (static / "md.js").write_text("var x=1;", encoding="utf-8")
    articles = {"특허법#제30조": {"article_id": "특허법#제30조", "label": "특허법 제30조", "text": "원문", "source": "출처"}}
    srv = make_server(Settings(port=0), ask_ok, articles.get, static_dir=static)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", srv
    srv.shutdown()
    srv.server_close()


def call(url, data=None, headers=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def test_server_binds_localhost_only_and_serves_static_and_health(server):
    base, srv = server
    assert srv.server_address[0] == "127.0.0.1"
    assert call(base + "/health")[0] == 200
    status, data, h = call(base + "/")
    assert status == 200 and "화면" in data.decode() and h["Content-Type"].startswith("text/html")
    assert call(base + "/md.js")[2]["Content-Type"].startswith("text/javascript")
    assert call(base + "/" + urllib.parse.quote("없는경로"))[0] == 404


def test_ask_requires_json_content_type_and_valid_length(server):
    base, _ = server
    payload = body(message="질문")
    assert call(base + "/api/ask", payload, {"Content-Type": "text/plain"}, "POST")[0] == 415  # 다른 웹페이지가 몰래 보내는 요청 차단
    assert call(base + "/api/ask", payload, {"Content-Type": "application/json; charset=utf-8"}, "POST")[0] == 200
    status, data, _ = call(base + "/api/ask", payload, {"Content-Type": "application/json"}, "POST")
    assert json.loads(data)["status"] == "answered"
    big = b"x" * 1_000_001
    try:  # 서버는 본문을 읽기 전에 거절하므로 클라이언트가 전송 중 연결 끊김을 볼 수도 있다(둘 다 거절로 본다)
        assert call(base + "/api/ask", big, {"Content-Type": "application/json"}, "POST")[0] == 400
    except urllib.error.URLError:
        pass


def test_article_endpoint_found_missing_and_unknown(server):
    base, _ = server
    q = urllib.parse.quote("특허법#제30조")
    status, data, _ = call(base + f"/api/article?id={q}")
    assert status == 200 and json.loads(data)["label"] == "특허법 제30조"
    assert call(base + "/api/article?id=" + urllib.parse.quote("특허법#제9999조"))[0] == 404
    assert call(base + "/api/article")[0] == 400
