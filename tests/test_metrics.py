import pytest

from src.eval.metrics import article_of, hit_at_k, mrr, rank_of_gold, summarize


def test_article_of_strips_paragraph_suffix():
    assert article_of("특허법#제29조") == "특허법#제29조"
    assert article_of("특허법#제29조#제1항") == "특허법#제29조"
    assert article_of("특허법#제132조의17#제2항") == "특허법#제132조의17"


def test_rank_is_one_based_position_of_first_gold():
    ranked = ["특허법#제1조", "특허법#제29조", "특허법#제30조"]
    assert rank_of_gold(ranked, ["특허법#제29조"]) == 2


def test_paragraph_chunks_of_same_article_count_once():
    # 제29조 항 청크 3개가 앞서도 제47조는 2위여야 한다(중복 제거)
    ranked = ["특허법#제29조#제1항", "특허법#제29조#제2항", "특허법#제29조#제3항", "특허법#제47조"]
    assert rank_of_gold(ranked, ["특허법#제47조"]) == 2


def test_paragraph_chunk_of_gold_article_counts_as_hit():
    ranked = ["특허법#제1조", "특허법#제29조#제2항"]
    assert rank_of_gold(ranked, ["특허법#제29조"]) == 2


def test_missing_gold_returns_none():
    assert rank_of_gold(["특허법#제1조", "특허법#제2조"], ["특허법#제29조"]) is None


def test_multiple_gold_uses_best_rank():
    ranked = ["특허법#제1조", "특허법#제61조", "시행령#제9조"]
    assert rank_of_gold(ranked, ["시행령#제9조", "특허법#제61조"]) == 2


def test_same_label_in_different_law_is_not_a_match():
    assert rank_of_gold(["시행령#제5조"], ["특허법#제5조"]) is None


def test_hit_at_k():
    assert hit_at_k(1, 1) and hit_at_k(3, 3) and not hit_at_k(4, 3)
    assert not hit_at_k(None, 5)


def test_mrr_counts_missing_as_zero():
    assert mrr([1, 2, None, 4]) == pytest.approx((1 + 0.5 + 0 + 0.25) / 4)
    assert mrr([]) == 0.0


def test_summarize_defaults():
    s = summarize([1, 3, None, 6])
    assert s["n"] == 4
    assert s["hit@1"] == 1 and s["hit@3"] == 2 and s["hit@5"] == 2
    assert s["mrr"] == pytest.approx((1 + 1 / 3 + 0 + 1 / 6) / 4)


def test_branch_number_article_is_not_prefix_matched():
    ranked = ["특허법#제132조의17#제1항", "특허법#제132조"]
    assert rank_of_gold(ranked, ["특허법#제132조"]) == 2
    assert rank_of_gold(ranked, ["특허법#제132조의17"]) == 1


def test_empty_ranking_and_gold_in_paragraph_form():
    assert rank_of_gold([], ["특허법#제29조"]) is None
    ranked = ["특허법#제1조", "특허법#제1조#제2항", "특허법#제29조#제1항"]
    assert rank_of_gold(ranked, ["특허법#제29조#제1항"]) == 2


def test_both_gold_present_uses_earlier_one():
    ranked = ["시행령#제9조", "특허법#제61조"]
    assert rank_of_gold(ranked, ["특허법#제61조", "시행령#제9조"]) == 1


def test_malformed_ids_raise_instead_of_silently_missing():
    for bad in ["특허법", "제29조", "특허법#29", ""]:
        with pytest.raises(ValueError):
            article_of(bad)
    with pytest.raises(ValueError):
        rank_of_gold(["특허법#제1조"], ["특허법"])


def test_trailing_whitespace_is_normalized():
    assert rank_of_gold(["특허법#제29조 "], ["특허법#제29조"]) == 1


def test_mrr_rejects_nonpositive_rank_and_summarize_custom_ks():
    with pytest.raises(ValueError):
        mrr([0])
    s = summarize([2, None], ks=(2,))
    assert s == {"n": 2, "hit@2": 1, "mrr": 0.25}
    assert summarize([])["n"] == 0


def test_rank_of_gold_max_rank_cutoff_counts_articles():
    from src.eval.metrics import rank_of_gold
    ranked = ["법#제1조#제1항", "법#제1조#제2항", "법#제2조", "법#제3조"]
    assert rank_of_gold(ranked, ["법#제3조"]) == 3
    assert rank_of_gold(ranked, ["법#제3조"], max_rank=3) == 3
    assert rank_of_gold(ranked, ["법#제3조"], max_rank=2) is None


def test_rank_of_gold_max_rank_multiple_gold_and_edges():
    from src.eval.metrics import rank_of_gold
    ranked = ["법#제1조", "법#제2조", "법#제3조", "법#제9조"]
    assert rank_of_gold(ranked, ["법#제9조", "법#제3조"], max_rank=3) == 3
    assert rank_of_gold(ranked, ["법#제9조", "법#제3조"], max_rank=2) is None
    assert rank_of_gold(ranked, ["법#제1조"], max_rank=1) == 1
    assert rank_of_gold(ranked, ["법#제2조"], max_rank=1) is None
