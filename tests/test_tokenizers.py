import pytest

from src.retrieval.tokenizers import char_ngram_tokenizer, kiwi_tokenizer


def test_char_bigram_basic_and_short_words():
    tok = char_ngram_tokenizer(2)
    assert tok("공공질서에") == ["공공", "공질", "질서", "서에"]
    assert tok("수 있나요?") == ["수", "있나", "나요"]


def test_char_ngram_strips_punctuation_and_empty():
    tok = char_ngram_tokenizer(2)
    assert tok("(특허)") == ["특허"]
    assert tok("?!") == []
    assert tok("") == []


def test_char_trigram():
    assert char_ngram_tokenizer(3)("특허출원") == ["특허출", "허출원"]


kiwipiepy = pytest.importorskip("kiwipiepy")


def test_kiwi_drops_particles_and_endings_keeps_content_words():
    toks = kiwi_tokenizer("공공질서에 어긋나는 발명도 특허가 되나요?")
    assert {"공공", "질서", "발명", "특허"} <= set(toks)
    assert "에" not in toks and "도" not in toks and "?" not in toks


def test_kiwi_query_and_statute_wording_share_tokens():
    # D11: 질문의 "공공질서에"와 조문의 "공공의 질서"가 같은 토큰으로 이어져야 한다.
    q = set(kiwi_tokenizer("공공질서에 어긋나는 발명도 특허가 되나요?"))
    d = set(kiwi_tokenizer("공공의 질서 또는 선량한 풍속에 어긋나거나"))
    assert {"공공", "질서"} <= q & d
