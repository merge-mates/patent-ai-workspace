"""OpenAI 임베딩 호출 (requests 사용, SDK 불필요).

- API 키는 .env 의 OPENAI_API_KEY 에서만 읽고 출력·저장하지 않는다.
- 보내는 것은 공개 법령 텍스트와 질문뿐이다(data-notes.md 데이터 정책).
"""
import time
from pathlib import Path

import requests

URL = "https://api.openai.com/v1/embeddings"
DEFAULT_MODEL = "text-embedding-3-small"
BATCH_SIZE = 64


def load_api_key(env_path: Path = Path(".env")) -> str:
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENAI_API_KEY="):
            key = line.split("=", 1)[1].strip().strip("\"'")
            if key:
                return key
    raise RuntimeError(".env 에 OPENAI_API_KEY 값이 없습니다.")


def batches(items: list, size: int = BATCH_SIZE):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def embed_texts(texts: list[str], model: str, api_key: str, retries: int = 3,
                post=requests.post) -> list[list[float]]:
    """texts -> 같은 순서의 벡터 목록. 429/5xx 는 늘려 가며 재시도. 오류 메시지에 키를 넣지 않는다."""
    vectors: list[list[float]] = []
    for batch in batches(texts):
        for attempt in range(retries + 1):
            resp = post(URL, headers={"Authorization": f"Bearer {api_key}"},
                        json={"model": model, "input": batch, "encoding_format": "float"}, timeout=60)
            if resp.status_code == 200:
                data = sorted(resp.json()["data"], key=lambda d: d["index"])
                vectors.extend(d["embedding"] for d in data)
                break
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"임베딩 호출 실패: HTTP {resp.status_code} {resp.text[:200]}")
    return vectors
