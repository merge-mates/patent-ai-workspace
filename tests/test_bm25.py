from src.retrieval.bm25 import Bm25Retriever, whitespace_tokenizer

CHUNKS = [
    {"chunk_id": "법#제1조", "text": "특허 출원 심사"},
    {"chunk_id": "법#제2조", "text": "상표 등록 심판"},
    {"chunk_id": "법#제3조", "text": "특허 심판 청구"},
    {"chunk_id": "법#제4조", "text": "특허 특허 특허 심사 청구 출원"},
    {"chunk_id": "법#제5조", "text": "디자인 보호"},
]


def test_whitespace_tokenizer_keeps_particles_attached():
    assert whitespace_tokenizer("특허를 받을 수 있나요?") == ["특허를", "받을", "수", "있나요?"]


def test_more_matching_terms_rank_higher():
    r = Bm25Retriever(CHUNKS)
    ids = [cid for cid, _ in r.search("출원 심사")]
    assert ids[0] in ("법#제1조", "법#제4조")
    assert ids.index("법#제1조") < ids.index("법#제3조") if "법#제3조" in ids else True


def test_zero_score_chunks_are_excluded():
    r = Bm25Retriever(CHUNKS)
    ids = [cid for cid, _ in r.search("상표")]
    assert ids == ["법#제2조"]
    assert r.search("존재하지않는말") == []


def test_ties_follow_input_order_and_are_deterministic():
    # BM25 는 모든 문서에 나오는 말에 점수를 못 주므로, 다른 문서를 충분히 섞는다.
    chunks = [{"chunk_id": f"법#제{i}조", "text": "같은 문장"} for i in range(1, 5)]
    chunks += [{"chunk_id": f"법#제{i}조", "text": f"다른 내용{i}"} for i in range(5, 15)]
    r = Bm25Retriever(chunks)
    first = r.search("문장")
    assert [cid for cid, _ in first] == [f"법#제{i}조" for i in range(1, 5)]
    assert first == r.search("문장")


def test_top_n_limits_results():
    r = Bm25Retriever(CHUNKS)
    assert len(r.search("특허", top_n=2)) == 2


def test_custom_tokenizer_is_used():
    r = Bm25Retriever(CHUNKS, tokenizer=lambda t: list(t.replace(" ", "")))
    assert r.search("상")[0][0] == "법#제2조"
