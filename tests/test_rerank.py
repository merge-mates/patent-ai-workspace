from src.retrieval.rerank import apply_rerank, build_links, law_first, link_pairs

L1, L2 = "특허법#제1조", "특허법#제2조"
D5, R9 = "특허법 시행령#제5조", "특허법 시행규칙#제9조"


def test_law_first_is_stable_partition_within_top_k_only():
    ranked = [R9, D5, L1, L2]
    assert law_first(ranked, top_k=3) == [L1, R9, D5, L2]
    assert law_first(ranked, top_k=10) == [L1, L2, R9, D5]


def test_build_links_follows_law_and_decree_references_both_ways():
    chunks = [
        {"chunk_id": L1, "text": "특허법 제1조(목적)\n..."},
        {"chunk_id": D5, "text": "특허법 시행령 제5조(x)\n법 제1조제2항에 따라 ..."},
        {"chunk_id": R9, "text": "특허법 시행규칙 제9조(y)\n영 제5조 및 「특허법」 제2조의 ... 법 제99조"},
        {"chunk_id": L2, "text": "특허법 제2조(정의)\n..."},
    ]
    links = build_links(chunks)
    assert links[L1] == {D5} and links[D5] == {L1, R9} and links[R9] == {D5, L2}  # 제99조는 코퍼스에 없어 무시
    assert links[L2] == {R9}


def test_link_pairs_promotes_one_partner_right_after_a_lead_item():
    links = {L1: {D5}, D5: {L1}}
    ranked = [L1, R9, L2, "특허법#제3조", D5]
    assert link_pairs(ranked, links, lead_k=3, window=10) == [L1, D5, R9, L2, "특허법#제3조"]


def test_link_pairs_ignores_partner_outside_window_and_non_lead_items():
    links = {"특허법#제3조": {D5}, D5: {"특허법#제3조"}, L1: {"X#제1조"}}
    ranked = [L1, R9, L2, "특허법#제3조", D5]
    assert link_pairs(ranked, links, lead_k=3, window=10) == ranked  # 제3조는 lead 가 아님
    assert link_pairs([L1, R9, L2, D5], {L1: {D5}, D5: {L1}}, lead_k=3, window=3) == [L1, R9, L2, D5]


def test_apply_rerank_none_and_unknown():
    assert apply_rerank("none", [L1]) == [L1]
    import pytest
    with pytest.raises(ValueError):
        apply_rerank("zzz", [L1])
