"""LLM 재순위(Phase 6 실험 ③-d): 검색 상위 후보 조문 N개를 질문과 함께 LLM 에 보여 주고 관련성 순서로 다시 정렬한다.

- 프롬프트는 PROMPT_VERSION 으로 고정한다(개발 결과를 보고 고치면 새 버전으로 기록).
- LLM 에 보내는 것은 원 질문 문장과 후보 조문의 공개 법령 텍스트뿐이다. 정답·평가 정보는 넣지 않는다.
- 응답에서 숫자를 순서대로 읽어 후보 번호로 쓴다. 범위 밖·중복 번호는 버리고, 빠진 후보는 원래 순서대로 뒤에 붙인다.
  (LLM 이 엉뚱한 응답을 해도 후보를 잃어버리지 않게 한다.)
- API 키는 오류 메시지에 넣지 않는다.
"""
import re
import time

import requests

from src.eval.metrics import article_of

URL = "https://api.openai.com/v1/chat/completions"
PROMPT_VERSION = "v1"
MAX_CHARS = 1500  # 후보 한 개 조문 글자 수 상한(긴 조문은 앞부분만 보여 줌)

SYSTEM_PROMPT = (
    "당신은 한국 특허법령(특허법, 특허법 시행령, 특허법 시행규칙) 검색 결과를 다시 정렬한다. "
    "질문과 후보 조문 여러 개가 번호와 함께 주어진다. 질문에 가장 직접적으로 답하는 조문이 앞에 오도록, "
    "후보 번호를 관련성이 높은 순서대로 쉼표로 나열한다. 질문이 묻는 내용에 직접 답하는 조문은 위로, "
    "주제만 비슷한 조문은 아래로 보낸다. 모든 후보 번호를 한 번씩 쓰고, 번호와 쉼표 외의 말은 쓰지 않는다."
)


def article_texts(chunks: list[dict], max_chars: int = MAX_CHARS) -> dict[str, str]:
    """조문 id -> 조문 전체 글(청크를 순서대로 이음, 항 청크마다 반복되는 첫 줄 머리글은 한 번만). max_chars 로 자름."""
    parts: dict[str, list[str]] = {}
    for c in chunks:
        art = article_of(c["chunk_id"])
        head, sep, body = c["text"].partition("\n")
        if art in parts and sep:
            parts[art].append(body)
        else:
            parts[art] = [c["text"]]
    return {a: "\n".join(p)[:max_chars] for a, p in parts.items()}


def build_messages(question: str, candidates: list[tuple[str, str]]) -> list[dict]:
    """candidates: [(표시 이름, 본문)] 순서대로 [1], [2], … 번호를 붙인다."""
    body = "\n\n".join(f"[{i}] {label}\n{text}" for i, (label, text) in enumerate(candidates, start=1))
    user = f"질문: {question}\n\n후보 조문:\n{body}"
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def parse_order(raw: str, n: int) -> list[int]:
    """응답 -> 0부터 시작하는 후보 인덱스 순서(길이 n). 범위 밖·중복은 버리고 빠진 것은 원래 순서로 뒤에 붙인다."""
    seen: list[int] = []
    for tok in re.findall(r"\d+", raw):
        i = int(tok) - 1
        if 0 <= i < n and i not in seen:
            seen.append(i)
    return seen + [i for i in range(n) if i not in seen]


def call_llm(messages: list[dict], model: str, api_key: str, retries: int = 3, post=requests.post,
             temperature: float | None = 0) -> str:
    body = {"model": model, "messages": messages}
    if temperature is not None:
        body["temperature"] = temperature
    for attempt in range(retries + 1):
        resp = post(URL, headers={"Authorization": f"Bearer {api_key}"}, json=body, timeout=120)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"]
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
            time.sleep(2 ** attempt)
            continue
        raise RuntimeError(f"재순위 호출 실패: HTTP {resp.status_code} {resp.text[:200]}")
    raise RuntimeError("재순위 호출 실패: 재시도 초과")


def llm_rerank(question: str, ranked: list[str], texts: dict[str, str], model: str, api_key: str,
               window: int = 10, call=call_llm) -> tuple[list[str], str]:
    """ranked(조문 id 순위)의 앞 window 개를 LLM 으로 재정렬한다. (새 순위, LLM 원문 응답)을 돌려준다."""
    head, tail = ranked[:window], ranked[window:]
    cands = [(a.replace("#", " "), texts[a]) for a in head]
    raw = call(build_messages(question, cands), model, api_key)
    order = parse_order(raw, len(head))
    return [head[i] for i in order] + tail, raw
