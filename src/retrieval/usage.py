"""LLM·임베딩 호출의 토큰 사용량 기록(토큰 비용 측정용).

호출 함수의 시그니처는 바꾸지 않는다: 호출하는 쪽이 `with capture() as recs:` 로 감싸면 그 안에서 일어난 호출의
사용량이 recs 에 쌓이고, 감싸지 않으면 기록은 조용히 무시된다(contextvar 라서 스레드마다 따로).
가격표(PRICES_PER_MILLION)에 없는 모델은 비용을 계산하지 않고 이름만 알려 준다(가격을 지어내지 않는다).
"""
import contextlib
import contextvars

_records: contextvars.ContextVar = contextvars.ContextVar("usage_records", default=None)

# 100만 토큰당 (입력, 출력) 달러. 출처: Anthropic 가격표(2026-11-03 기준 캐시)와 OpenAI 임베딩 공개 가격.
# 가격이 바뀌거나 모델을 추가할 때는 이 표만 고치면 된다. 표에 없는 모델은 "가격 미등록"으로 따로 보고한다.
PRICES_PER_MILLION: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "text-embedding-3-small": (0.02, 0.0),
}


def record(stage: str, model: str, input_tokens: int, output_tokens: int) -> None:
    recs = _records.get()
    if recs is not None:
        recs.append({"stage": stage, "model": model, "input_tokens": int(input_tokens), "output_tokens": int(output_tokens)})


def record_openai_chat(stage: str, model: str, data: dict) -> None:
    """OpenAI chat completions 응답의 usage(prompt_tokens, completion_tokens)를 기록한다. usage 가 없으면 무시."""
    u = data.get("usage") if isinstance(data, dict) else None
    if u:
        record(stage, model, u.get("prompt_tokens", 0), u.get("completion_tokens", 0))


def record_openai_embedding(model: str, data: dict) -> None:
    u = data.get("usage") if isinstance(data, dict) else None
    if u:
        record("embed", model, u.get("prompt_tokens", 0), 0)


def record_anthropic(stage: str, model: str, data: dict) -> None:
    """Claude Messages 응답의 usage(input_tokens, output_tokens; 생각 토큰은 출력에 포함됨)를 기록한다."""
    u = data.get("usage") if isinstance(data, dict) else None
    if u:
        record(stage, model, u.get("input_tokens", 0), u.get("output_tokens", 0))


@contextlib.contextmanager
def capture():
    """이 안에서 일어난 호출의 사용량을 리스트로 모은다."""
    recs: list[dict] = []
    token = _records.set(recs)
    try:
        yield recs
    finally:
        _records.reset(token)


def _empty() -> dict:
    return {"by_stage": {}, "input_tokens": 0, "output_tokens": 0}


def summarize(recs: list[dict]) -> dict:
    """기록 -> {"by_stage": {"단계:모델": {calls, input_tokens, output_tokens}}, "input_tokens", "output_tokens"}."""
    out = _empty()
    for r in recs:
        s = out["by_stage"].setdefault(f"{r['stage']}:{r['model']}", {"calls": 0, "input_tokens": 0, "output_tokens": 0})
        s["calls"] += 1
        s["input_tokens"] += r["input_tokens"]
        s["output_tokens"] += r["output_tokens"]
        out["input_tokens"] += r["input_tokens"]
        out["output_tokens"] += r["output_tokens"]
    return out


def merge(a: dict, b: dict) -> dict:
    """두 요약을 더한다(비어 있는 요약, 예: 사용량이 없던 예전 검색 캐시도 허용)."""
    out = _empty()
    for part in (a or {}, b or {}):
        for key, s in part.get("by_stage", {}).items():
            t = out["by_stage"].setdefault(key, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
            for k in ("calls", "input_tokens", "output_tokens"):
                t[k] += s[k]
        out["input_tokens"] += part.get("input_tokens", 0)
        out["output_tokens"] += part.get("output_tokens", 0)
    return out


def cost_of(summary: dict) -> tuple[float, list[str]]:
    """요약 -> (가격표에 있는 모델의 달러 합계, 가격이 등록되지 않은 모델 이름들)."""
    usd, unpriced = 0.0, []
    for key, s in summary.get("by_stage", {}).items():
        model = key.split(":", 1)[1]
        price = PRICES_PER_MILLION.get(model)
        if price is None:
            if model not in unpriced:
                unpriced.append(model)
            continue
        usd += s["input_tokens"] / 1e6 * price[0] + s["output_tokens"] / 1e6 * price[1]
    return usd, unpriced
