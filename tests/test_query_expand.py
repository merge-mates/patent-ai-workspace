import pytest

from src.retrieval.query_expand import (MAX_TERMS, queries_by_id, PROMPT_VERSION, build_messages, expand_one,
                                        expanded_query, has_article_number, parse_terms)


class FakeResp:
    def __init__(self, status, content=None, text=""):
        self.status_code, self._c, self.text = status, content, text

    def json(self):
        return {"choices": [{"message": {"content": self._c}}]}


def test_parse_terms_splits_strips_dedupes_and_caps():
    raw = "침해 금지 청구, 예방 청구\n 침해 금지 청구 ,  ,손해배상,a,b,c,d,e,f"
    terms = parse_terms(raw)
    assert terms[:3] == ["침해 금지 청구", "예방 청구", "손해배상"]
    assert len(terms) == MAX_TERMS == 8


def test_parse_terms_removes_list_markers_and_article_numbers():
    terms = parse_terms("1. 공동출원, - 공유자, 제44조, 특허법 제97조의2 보호범위")
    assert terms == ["공동출원", "공유자"]


def test_has_article_number():
    assert has_article_number("제126조")
    assert has_article_number("제 63조의2")
    assert not has_article_number("보호범위 조문")


def test_build_messages_contains_only_the_question_and_fixed_instruction():
    msgs = build_messages("그만두라고 요구할 수 있나요?")
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert msgs[1]["content"] == "그만두라고 요구할 수 있나요?"
    assert "조문 번호" in msgs[0]["content"]
    assert PROMPT_VERSION == "v1"


def test_expanded_query_appends_terms_on_new_line_and_keeps_question():
    assert expanded_query("질문?", ["a", "b"]) == "질문?\na, b"
    assert expanded_query("질문?", []) == "질문?"


def test_expand_one_sends_temperature_zero_and_returns_text():
    seen = {}

    def post(url, headers, json, timeout):
        seen.update(json)
        return FakeResp(200, "보호범위, 청구범위")

    assert expand_one("q", "m", "KEY", post=post) == "보호범위, 청구범위"
    assert seen["temperature"] == 0 and seen["model"] == "m"


def test_expand_one_retry_and_error_hides_key(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    seq = [FakeResp(429), FakeResp(200, "x")]
    assert expand_one("q", "m", "SECRETKEY", post=lambda *a, **k: seq.pop(0)) == "x"
    with pytest.raises(RuntimeError) as e:
        expand_one("q", "m", "SECRETKEY", post=lambda *a, **k: FakeResp(401, text="bad"))
    assert "SECRETKEY" not in str(e.value)


def test_expand_one_can_omit_temperature():
    seen = {}

    def post(url, headers, json, timeout):
        seen.update(json)
        return FakeResp(200, "x")

    expand_one("q", "m", "KEY", post=post, temperature=None)
    assert "temperature" not in seen


def test_queries_by_id_maps_in_order_and_rejects_missing_or_duplicate():
    exp = {"items": [{"id": "D01", "query": "a"}, {"id": "D02", "query": "b"}]}
    assert queries_by_id(exp, ["D02", "D01"]) == {"D02": "b", "D01": "a"}
    with pytest.raises(ValueError):
        queries_by_id(exp, ["D03"])
    with pytest.raises(ValueError):
        queries_by_id({"items": [{"id": "D01", "query": "a"}, {"id": "D02", "query": "a"}]}, ["D01", "D02"])


def test_prompt_v2_is_selectable_and_default_stays_v1():
    from src.retrieval.query_expand import PROMPTS, PROMPT_VERSION, SYSTEM_PROMPT, build_messages
    assert PROMPT_VERSION == "v1" and PROMPTS["v1"] == SYSTEM_PROMPT
    assert build_messages("질문")[0]["content"] == PROMPTS["v1"]
    v2 = build_messages("질문", "v2")[0]["content"]
    assert v2 == PROMPTS["v2"] and v2 != PROMPTS["v1"]
    assert "시행령" in v2 and "시행규칙" in v2 and "실무" in v2
