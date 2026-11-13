import json
from pathlib import Path

import pytest

from src.law_api.chunker import strip_amend_tags
from src.retrieval.variants import drop_header, make_noheader

CHUNKS = Path("data/processed/chunks_특허법_279827_20251111.jsonl")
NOTAGS = Path("data/processed/chunks_특허법_279827_20251111_notags.jsonl")


def test_drop_header_keeps_body_exactly():
    assert drop_header("특허법 제32조(특허를 받을 수 없는 발명)\n공공의 질서 ...\n둘째 줄") == "공공의 질서 ...\n둘째 줄"


def test_drop_header_without_newline_is_unchanged():
    assert drop_header("특허법 제1조(목적)") == "특허법 제1조(목적)"


def test_make_noheader_keeps_ids_and_metadata_and_does_not_mutate_input():
    src = [{"chunk_id": "특허법#제1조", "text": "특허법 제1조(목적)\n본문", "metadata": {"label": "제1조"}}]
    out = make_noheader(src)
    assert out == [{"chunk_id": "특허법#제1조", "text": "본문", "metadata": {"label": "제1조"}}]
    assert src[0]["text"].startswith("특허법 제1조")


@pytest.mark.skipif(not (CHUNKS.exists() and NOTAGS.exists()), reason="청크 파일 없음(gitignore 대상)")
def test_real_corpus_variants_are_aligned_with_baseline():
    base = [json.loads(l) for l in CHUNKS.read_text(encoding="utf-8").splitlines()]
    nohead = make_noheader(base)
    notags = [json.loads(l) for l in NOTAGS.read_text(encoding="utf-8").splitlines()]
    assert [c["chunk_id"] for c in nohead] == [c["chunk_id"] for c in base] == [c["chunk_id"] for c in notags]
    assert all(c["text"].strip() for c in nohead)
    assert all(not c["text"].startswith("특허법 제") or "\n" not in b["text"] for c, b in zip(nohead, base))
    # V2: 변형은 기준에서 날짜 태그만 뺀 것이어야 한다(태그 제거 규칙과 같은 결과)
    assert all(strip_amend_tags(b["text"]) == n["text"] for b, n in zip(base, notags))


def test_make_context_prepends_chapter_path_and_keeps_others():
    from src.retrieval.variants import make_context
    src = [{"chunk_id": "a", "text": "특허법 제1조(목적)\n본문", "metadata": {"chapter": "제1장 총칙", "section": "제1절 가", "subsection": None}},
           {"chunk_id": "b", "text": "특허법 제2조(x)\n본문", "metadata": {"chapter": None, "section": None, "subsection": None}}]
    out = make_context(src)
    assert out[0]["text"] == "제1장 총칙 > 제1절 가\n특허법 제1조(목적)\n본문"
    assert out[1]["text"] == src[1]["text"] and src[0]["text"].startswith("특허법 제1조")
