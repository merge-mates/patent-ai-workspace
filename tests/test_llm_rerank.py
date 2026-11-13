import pytest

from src.retrieval.llm_rerank import (SYSTEM_PROMPT, article_texts, build_messages, call_llm, llm_rerank,
                                      parse_order)


def test_parse_order_reads_numbers_drops_invalid_and_appends_missing():
    assert parse_order("3, 1, 2", 3) == [2, 0, 1]
    assert parse_order("2, 2, 9, 0, 1", 4) == [1, 0, 2, 3]  # 중복·범위 밖 버림, 빠진 것은 원래 순서로
    assert parse_order("모르겠습니다", 3) == [0, 1, 2]
    assert parse_order("[2] > [1]", 2) == [1, 0]


def test_article_texts_joins_paragraph_chunks_with_single_header_and_truncates():
    chunks = [{"chunk_id": "특허법#제42조#제1항", "text": "특허법 제42조(특허출원)\n① 가"},
              {"chunk_id": "특허법#제42조#제2항", "text": "특허법 제42조(특허출원)\n② 나"},
              {"chunk_id": "특허법#제1조", "text": "특허법 제1조(목적)"}]
    t = article_texts(chunks)
    assert t["특허법#제42조"] == "특허법 제42조(특허출원)\n① 가\n② 나"
    assert t["특허법#제1조"] == "특허법 제1조(목적)"
    assert article_texts(chunks, max_chars=5)["특허법#제42조"] == "특허법 제"


def test_build_messages_numbers_candidates_and_contains_no_gold_info():
    m = build_messages("질문 문장", [("특허법 제1조", "가"), ("특허법 시행령 제2조", "나")])
    assert m[0]["content"] == SYSTEM_PROMPT
    assert "질문: 질문 문장" in m[1]["content"] and "[1] 특허법 제1조\n가" in m[1]["content"] and "[2] 특허법 시행령 제2조\n나" in m[1]["content"]


def test_llm_rerank_reorders_window_and_keeps_tail():
    ranked = ["A#제1조", "A#제2조", "A#제3조", "A#제4조"]
    texts = {a: a for a in ranked}
    new, raw = llm_rerank("q", ranked, texts, "m", "k", window=3, call=lambda msgs, model, key: "3,1")
    assert new == ["A#제3조", "A#제1조", "A#제2조", "A#제4조"] and raw == "3,1"


def test_call_llm_error_message_does_not_contain_key():
    class R:
        status_code = 401
        text = "unauthorized"
    with pytest.raises(RuntimeError) as e:
        call_llm([], "m", "SECRET-KEY", post=lambda *a, **k: R())
    assert "SECRET-KEY" not in str(e.value)
