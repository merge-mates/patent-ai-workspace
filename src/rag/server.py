"""챗봇 HTTP 서버(표준 http.server, 새 의존성 없음). 실행: python -m src.rag.server  (기본 http://localhost:3000)

POST /api/ask {"message", "history"?} -> {"status","answer_display","citations","seconds"}
GET  /api/article?id=<조문 id>        -> 조문 원문·출처(화면에서 인용 조문을 눌렀을 때)
GET  /health, GET / (화면), GET /md.js
검색·생성·원문 조회는 함수로 주입받는다(테스트에서 가짜로 바꿈). 인증이 없으므로 127.0.0.1 에서만 연다.
방어 장치와 구조는 이전에 만든 간단한 챗봇 실습 코드를 참고했다(Content-Type 검사, 본문·질문 길이 제한, 소켓 타임아웃,
짧은 한국어 오류, 예외 종류만 로그).
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlsplit

MAX_BODY = 1_000_000
STATIC_FILES = {  # 서빙하는 화면 파일(이 목록에 있는 것만)
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/md.js": ("md.js", "text/javascript; charset=utf-8"),
}
RESPONSE_FIELDS = ("status", "answer_display", "citations", "seconds")  # 화면에 필요한 것만 보낸다


def _log(msg: str) -> None:
    """원인 파악용 로그. 예외 메시지에는 키가 섞일 수 있으니 예외 종류만 남긴다."""
    print(msg, file=sys.stderr, flush=True)


def handle_ask(raw: bytes, *, ask: Callable[[str], dict], max_message_len: int) -> tuple[int, dict]:
    """요청 본문 -> (HTTP 상태, 응답). history 는 형식만 확인하고 쓰지 않는다(대화 기억은 다음 단계)."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        data = None
    if not isinstance(data, dict):
        return 400, {"error": "요청 형식이 올바르지 않습니다"}
    message = data.get("message")
    if not isinstance(message, str) or not message.strip() or len(message) > max_message_len:
        return 400, {"error": f"message 는 1~{max_message_len}자의 문자열이어야 합니다"}
    if "history" in data and not isinstance(data["history"], list):
        return 400, {"error": "history 는 목록이어야 합니다"}
    try:
        result = ask(message.strip())
    except Exception as e:
        _log(f"[오류] 답변 생성 실패: {type(e).__name__}")
        return 502, {"error": "답변을 만들지 못했습니다. 잠시 후 다시 시도해 주세요."}
    return 200, {k: result[k] for k in RESPONSE_FIELDS}


def make_server(settings, ask: Callable[[str], dict], get_article_fn: Callable[[str], dict | None],
                static_dir: Path = Path(__file__).parent / "web") -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        timeout = 30  # 몸통을 덜 보내고 멈춘 클라이언트가 스레드를 붙잡지 않게 한다

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, obj: dict) -> None:
            self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            parts = urlsplit(self.path)
            if parts.path == "/health":
                self._json(200, {"status": "ok"})
            elif parts.path == "/api/article":
                ids = parse_qs(parts.query).get("id")
                if not ids or not ids[0]:
                    self._json(400, {"error": "id 가 필요합니다"})
                    return
                article = get_article_fn(ids[0])
                if article is None:
                    self._json(404, {"error": "찾을 수 없습니다"})
                else:
                    self._json(200, article)
            elif parts.path in STATIC_FILES:
                name, ctype = STATIC_FILES[parts.path]
                try:
                    body = (static_dir / name).read_bytes()
                except OSError:
                    self._json(404, {"error": "찾을 수 없습니다"})
                    return
                self._send(200, body, ctype)
            else:
                self._json(404, {"error": "찾을 수 없습니다"})

        def do_POST(self):
            if urlsplit(self.path).path != "/api/ask":
                self._json(404, {"error": "찾을 수 없습니다"})
                return
            # 다른 웹페이지가 text/plain 등으로 몰래 보내는 요청(API 비용 소모)을 막는다.
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
                self._json(415, {"error": "Content-Type 은 application/json 이어야 합니다"})
                return
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY:
                self._json(400, {"error": "요청 형식이 올바르지 않습니다"})
                return
            raw = self.rfile.read(length)
            try:
                status, body = handle_ask(raw, ask=ask, max_message_len=settings.max_message_len)
            except Exception as e:
                _log(f"[오류] 처리되지 않은 예외: {type(e).__name__}")
                status, body = 500, {"error": "서버 오류"}
            self._json(status, body)

        def log_message(self, fmt, *args):  # 요청 로그에 질문 내용이 남지 않게 기본 로그를 끈다
            pass

    return ThreadingHTTPServer(("127.0.0.1", settings.port), Handler)


def main() -> None:
    import os

    from src.rag.articles import get_article, load_articles
    from src.rag.ask import answer_question
    from src.rag.pipeline import build_pipeline
    from src.rag.settings import Settings, load_key

    try:
        settings = Settings(port=int(os.environ.get("CHATBOT_PORT", "3000")))
    except ValueError:
        print("시작할 수 없습니다: CHATBOT_PORT 는 숫자여야 합니다.", file=sys.stderr)
        raise SystemExit(1)
    try:
        pipeline = build_pipeline(settings)
        key = load_key("ANTHROPIC_API_KEY", settings.env_path)
        articles = load_articles(settings.article_corpus)
    except (RuntimeError, OSError) as e:
        print(f"시작할 수 없습니다: {type(e).__name__}: {e}", file=sys.stderr)
        raise SystemExit(1)

    try:
        server = make_server(settings, lambda q: answer_question(q, pipeline, settings, key),
                             lambda i: get_article(articles, i))
    except OSError:
        print(f"시작할 수 없습니다: 포트 {settings.port} 를 쓸 수 없습니다(이미 사용 중일 수 있음). "
              "CHATBOT_PORT=3001 처럼 다른 포트로 실행하세요.", file=sys.stderr)
        raise SystemExit(1)
    print(f"챗봇 서버 시작: http://localhost:{server.server_address[1]}  (종료: Ctrl+C)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
