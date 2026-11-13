import json
from pathlib import Path

import pytest

from src.law_api.chunker import (Article, Law, Paragraph, _circled_to_int, _output_name,
                                 build_chunks, load_law)

RAW = Path("data/raw/body_특허법_279827_20251111.json")
BASELINE = Path("data/processed/chunks_특허법_279827_20251111.jsonl")


def art(label="제29조", title="특허요건", lead="", paragraphs=(), number=29, deleted=False):
    return Article(label=label, number=number, branch=None, title=title, lead=lead,
                   paragraphs=tuple(paragraphs), deleted=deleted, source_key="k", effective_date="20251111")


def para(number, *lines, deleted=False):
    return Paragraph(number=number, lines=tuple(lines), deleted=deleted)


def law_of(*articles):
    return Law(name="특허법", mst="1", effective_date="20251111", articles=tuple(articles))


def test_circled_numbers():
    assert [_circled_to_int(c) for c in "①②⑩⑬⑳㉑㉟㊱㊿"] == [1, 2, 10, 13, 20, 21, 35, 36, 50]
    assert _circled_to_int(None) is None and _circled_to_int("가") is None and _circled_to_int("①②") is None


def test_two_or_more_live_paragraphs_split_one_chunk_each():
    law = law_of(art(paragraphs=[para("①", "① 첫째 <개정 2016.2.29>", "1. 호 하나"), para("②", "② 둘째")]))
    ch = build_chunks(law, strategy="paragraph")
    assert [c.chunk_id for c in ch] == ["특허법#제29조#제1항", "특허법#제29조#제2항"]
    assert ch[0].text == "특허법 제29조(특허요건)\n① 첫째 <개정 2016.2.29>\n1. 호 하나"
    assert ch[1].text == "특허법 제29조(특허요건)\n② 둘째"
    assert ch[0].metadata["paragraph_no"] == 1 and ch[1].metadata["strategy"] == "paragraph"
    assert ch[0].metadata["char_len"] == len(ch[0].text) and ch[0].metadata["label"] == "제29조"


def test_zero_or_one_live_paragraph_stays_article_chunk():
    one = art(label="제2조", number=2, lead="이 법에서", paragraphs=[para(None, "1. 정의")])
    zero = art(label="제1조", number=1, title="목적", lead="목적 본문")
    only_live = art(label="제3조", number=3, paragraphs=[para("①", "① 살아있음"), para("②", "② 삭제 <개정 2020.1.1>", deleted=True)])
    ch = build_chunks(law_of(zero, one, only_live), strategy="paragraph")
    assert [c.chunk_id for c in ch] == ["특허법#제1조", "특허법#제2조", "특허법#제3조"]
    assert "paragraph_no" in ch[0].metadata and ch[0].metadata["paragraph_no"] is None
    assert ch[1].text == "특허법 제2조(특허요건)\n이 법에서\n1. 정의"


def test_deleted_paragraph_is_skipped_but_numbers_keep():
    law = law_of(art(paragraphs=[para("①", "① 가"), para("②", "② 삭제 <개정 2020.1.1>", deleted=True), para("③", "③ 다")]))
    assert [c.chunk_id for c in build_chunks(law, strategy="paragraph")] == ["특허법#제29조#제1항", "특허법#제29조#제3항"]


def test_lead_is_repeated_in_every_paragraph_chunk():
    law = law_of(art(lead="공통 머리말", paragraphs=[para("①", "① 가"), para("②", "② 나")]))
    ch = build_chunks(law, strategy="paragraph")
    assert all(c.text.split("\n")[1] == "공통 머리말" for c in ch)


def test_unparseable_number_falls_back_to_position_and_duplicates_raise():
    ch = build_chunks(law_of(art(paragraphs=[para(None, "가"), para(None, "나")])), strategy="paragraph")
    assert [c.chunk_id for c in ch] == ["특허법#제29조#제1항", "특허법#제29조#제2항"]
    with pytest.raises(ValueError):
        build_chunks(law_of(art(paragraphs=[para("①", "가"), para("①", "나")])), strategy="paragraph")


def test_strip_tags_and_determinism():
    law = law_of(art(paragraphs=[para("①", "① 가 <개정 2016.2.29>"), para("②", "② 나")]))
    a = build_chunks(law, strategy="paragraph", strip_tags=True)
    assert a[0].text.endswith("① 가") and a == build_chunks(law, strategy="paragraph", strip_tags=True)


def test_article_strategy_unchanged_and_output_name():
    law = law_of(art(paragraphs=[para("①", "① 가"), para("②", "② 나")]))
    assert [c.chunk_id for c in build_chunks(law)] == ["특허법#제29조"]
    assert _output_name(Path("body_특허법_279827_20251111.json"), False, "paragraph") == "chunks_특허법_279827_20251111_paragraph.jsonl"
    assert _output_name(Path("body_특허법_279827_20251111.json"), True, "paragraph") == "chunks_특허법_279827_20251111_notags_paragraph.jsonl"
    assert _output_name(Path("body_특허법_279827_20251111.json"), False) == "chunks_특허법_279827_20251111.jsonl"


@pytest.mark.skipif(not (RAW.exists() and BASELINE.exists()), reason="원본/청크 파일 없음")
def test_real_law_counts_ids_and_article_strategy_matches_baseline():
    law = load_law(RAW)
    para_chunks = build_chunks(law, strategy="paragraph")
    ids = [c.chunk_id for c in para_chunks]
    assert len(ids) == len(set(ids))
    n_para = sum(1 for c in para_chunks if c.chunk_id.count("#") == 2)
    n_art = len(para_chunks) - n_para
    assert (n_para, n_art) == (679, 87)
    # 모든 조문이 (조문 청크 1개) 또는 (항 청크 2개 이상) 중 하나로 표현된다
    arts = {c.chunk_id.split("#")[1] for c in para_chunks}
    assert len(arts) == 268
    base = [json.loads(l) for l in BASELINE.read_text(encoding="utf-8").splitlines()]
    assert [c.chunk_id for c in build_chunks(law)] == [b["chunk_id"] for b in base]
    assert [c.text for c in build_chunks(law)] == [b["text"] for b in base]
    # 항 청크의 본문을 합치면 조문 청크 본문의 줄과 같은 줄 집합이다
    by_art: dict[str, list[str]] = {}
    for c in para_chunks:
        if c.chunk_id.count("#") == 2:
            by_art.setdefault(c.chunk_id.split("#")[1], []).extend(c.text.split("\n")[1:])
    for b in base:
        a = b["chunk_id"].split("#")[1]
        if a in by_art:
            assert by_art[a] == b["text"].split("\n")[1:], a
