import pytest

from src.retrieval import usage
from src.rag.generate import call_claude
from src.retrieval.llm_rerank import call_llm
from src.retrieval.openai_embed import embed_texts
from src.retrieval.query_expand import expand_one


class Resp:
    def __init__(self, body, code=200):
        self.status_code, self._b, self.text = code, body, ""

    def json(self):
        return self._b


def test_record_outside_capture_is_a_noop():
    usage.record("expand", "m", 10, 5)  # 에러 없이 무시


def test_capture_collects_records_and_summarize_groups_by_stage_and_model():
    with usage.capture() as recs:
        usage.record("expand", "gpt-x", 100, 20)
        usage.record("expand", "gpt-x", 50, 10)
        usage.record("generate", "claude-y", 1000, 300)
    s = usage.summarize(recs)
    assert s["by_stage"]["expand:gpt-x"] == {"calls": 2, "input_tokens": 150, "output_tokens": 30}
    assert s["by_stage"]["generate:claude-y"] == {"calls": 1, "input_tokens": 1000, "output_tokens": 300}
    assert (s["input_tokens"], s["output_tokens"]) == (1150, 330)


def test_merge_adds_summaries_together():
    a = usage.summarize([{"stage": "a", "model": "m", "input_tokens": 1, "output_tokens": 2}])
    b = usage.summarize([{"stage": "a", "model": "m", "input_tokens": 10, "output_tokens": 20},
                         {"stage": "b", "model": "n", "input_tokens": 5, "output_tokens": 0}])
    m = usage.merge(a, b)
    assert m["by_stage"]["a:m"] == {"calls": 2, "input_tokens": 11, "output_tokens": 22}
    assert m["by_stage"]["b:n"]["calls"] == 1 and m["input_tokens"] == 16 and m["output_tokens"] == 22
    assert usage.merge({}, {})["input_tokens"] == 0  # 비어 있는(예전 캐시) 요약도 합칠 수 있다


def test_http_call_functions_record_usage_from_responses():
    chat = {"choices": [{"message": {"content": "답"}}], "usage": {"prompt_tokens": 120, "completion_tokens": 30}}
    emb = {"data": [{"index": 0, "embedding": [0.1]}], "usage": {"prompt_tokens": 7, "total_tokens": 7}}
    claude = {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn",
              "usage": {"input_tokens": 900, "output_tokens": 250}}
    with usage.capture() as recs:
        expand_one("질문", "gpt-x", "k", post=lambda *a, **k: Resp(chat))
        call_llm([], "gpt-x", "k", post=lambda *a, **k: Resp(chat))
        embed_texts(["가"], "emb-m", "k", post=lambda *a, **k: Resp(emb))
        call_claude("s", "u", "claude-y", "k", post=lambda *a, **k: Resp(claude))
        call_claude("s", "u", "claude-opus", "k", stage="judge", post=lambda *a, **k: Resp(claude))
    got = {(r["stage"], r["model"]): (r["input_tokens"], r["output_tokens"]) for r in recs}
    assert got == {("expand", "gpt-x"): (120, 30), ("rerank", "gpt-x"): (120, 30), ("embed", "emb-m"): (7, 0),
                   ("generate", "claude-y"): (900, 250), ("judge", "claude-opus"): (900, 250)}


def test_missing_usage_field_does_not_break_calls():
    with usage.capture() as recs:
        assert expand_one("질문", "m", "k", post=lambda *a, **k: Resp({"choices": [{"message": {"content": "답"}}]})) == "답"
    assert recs == []


def test_cost_uses_known_prices_and_reports_unpriced_models():
    s = usage.summarize([{"stage": "generate", "model": "claude-sonnet-5-5", "input_tokens": 1_000_000, "output_tokens": 100_000},
                         {"stage": "expand", "model": "unknown-model", "input_tokens": 500, "output_tokens": 50}])
    usd, unpriced = usage.cost_of(s)
    assert usd == pytest.approx(2.0 + 1.0)  # $2/M 입력 + $10/M 출력(10만 토큰 = $1)
    assert unpriced == ["unknown-model"]
