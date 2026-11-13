"""질의 확장(V4): 일상어 질문 -> 법률 용어 목록을 LLM 으로 받아 질문 뒤에 덧붙인다.

- 프롬프트는 PROMPT_VERSION 으로 고정한다. 개발 결과를 보고 고치지 않는다(고치면 새 버전으로 기록).
- LLM 에 보내는 것은 질문 문장뿐이다. 정답·조문 본문·예시 질문은 넣지 않는다(예시 없는 zero-shot).
- 조문 번호("제N조") 형태는 출력에서 걸러낸다.
- API 키는 .env 에서만 읽고(openai_embed.load_api_key 재사용) 오류 메시지에 넣지 않는다.
"""
import re
import time

import requests

from src.retrieval import usage

URL = "https://api.openai.com/v1/chat/completions"
PROMPT_VERSION = "v1"
MAX_TERMS = 8

SYSTEM_PROMPT = (
    "당신은 한국 특허법 조문 검색을 돕는다. 사용자가 일상어로 쓴 질문을 보고, "
    "그 질문에 답하는 특허법 조문의 제목이나 본문에 나올 법한 법률 용어를 "
    f"쉼표로 구분해 최대 {MAX_TERMS}개 적는다. "
    "조문 번호(제N조)는 쓰지 않는다. 설명, 문장, 번호 매기기 없이 용어만 쓴다."
)

# v2(2026-11-13): 사용자가 변리사 등 특허 실무자라고 가정하고, 실무 용어·약칭을 조문에 쓰인 법령 용어로 바꾸게 한다.
# 법령 범위도 특허법·시행령·시행규칙으로 넓힌다. 예시 질문·정답은 넣지 않는다(v1과 같은 zero-shot).
SYSTEM_PROMPT_V2 = (
    "당신은 한국 특허법령(특허법, 특허법 시행령, 특허법 시행규칙) 조문 검색을 돕는다. "
    "사용자는 변리사 등 특허 실무자이며, 질문에 실무에서 쓰는 용어나 약칭이 들어 있을 수 있다. "
    "그 질문에 답하는 조문의 제목이나 본문에 실제로 쓰였을 법한 법령 용어로 바꾸거나 보충해 "
    f"쉼표로 구분해 최대 {MAX_TERMS}개 적는다. 실무 약칭은 정식 법령 용어로 푼다. "
    "조문 번호(제N조)는 쓰지 않는다. 설명, 문장, 번호 매기기 없이 용어만 쓴다."
)
PROMPTS = {"v1": SYSTEM_PROMPT, "v2": SYSTEM_PROMPT_V2}

_ARTICLE_NO = re.compile(r"제\s*\d+\s*조")
_LIST_MARK = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s*")


def has_article_number(text: str) -> bool:
    return bool(_ARTICLE_NO.search(text))


def parse_terms(raw: str, max_terms: int = MAX_TERMS) -> list[str]:
    """쉼표·줄바꿈으로 나누고 목록 표시를 지운 뒤, 조문 번호가 든 항목은 버리고 중복을 없앤다."""
    out: list[str] = []
    for part in re.split(r"[,\n]", raw):
        term = _LIST_MARK.sub("", part).strip()
        if not term or has_article_number(term) or term in out:
            continue
        out.append(term)
        if len(out) == max_terms:
            break
    return out


def build_messages(question: str, version: str = PROMPT_VERSION) -> list[dict]:
    return [{"role": "system", "content": PROMPTS[version]}, {"role": "user", "content": question}]


def expanded_query(question: str, terms: list[str]) -> str:
    return f"{question}\n{', '.join(terms)}" if terms else question


def expand_one(question: str, model: str, api_key: str, retries: int = 3, post=requests.post,
               temperature: float | None = 0, version: str = PROMPT_VERSION) -> str:
    """질문 1개 -> LLM 원문 응답. 429/5xx 는 늘려 가며 재시도. 오류 메시지에 키를 넣지 않는다."""
    body = {"model": model, "messages": build_messages(question, version)}
    if temperature is not None:  # 일부 모델(추론형)은 temperature 지정을 받지 않는다
        body["temperature"] = temperature
    for attempt in range(retries + 1):
        resp = post(URL, headers={"Authorization": f"Bearer {api_key}"}, json=body, timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            usage.record_openai_chat("expand", model, data)  # 토큰 사용량 기록(캡처 중일 때만)
            return data["choices"][0]["message"]["content"]
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
            time.sleep(2 ** attempt)
            continue
        raise RuntimeError(f"질의 확장 호출 실패: HTTP {resp.status_code} {resp.text[:200]}")
    raise RuntimeError("질의 확장 호출 실패: 재시도 초과")


def queries_by_id(exp: dict, question_ids: list[str]) -> dict[str, str]:
    """확장 파일(dict) -> {질문 id: 검색 질의}. 평가할 질문이 하나라도 빠져 있으면 오류."""
    by_id = {i["id"]: i["query"] for i in exp["items"]}
    missing = [q for q in question_ids if q not in by_id]
    if missing:
        raise ValueError(f"확장 질의가 없는 질문: {missing}")
    if len(set(by_id.values())) != len(by_id):
        raise ValueError("확장 질의 문장이 중복되어 질의 벡터를 문장으로 찾을 수 없습니다.")
    return {q: by_id[q] for q in question_ids}
