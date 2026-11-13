import json
from pathlib import Path

import pytest

from src.eval.questions import DEFAULT_PATH, load_questions

CHUNKS = Path("data/processed/chunks_특허법_279827_20251111.jsonl")


def test_counts_by_split():
    assert len(load_questions(split="dev")) == 32
    assert len(load_questions(split="holdout")) == 8
    assert len(load_questions()) == 40


def test_ids_unique_and_gold_nonempty():
    qs = load_questions()
    assert len({q.id for q in qs}) == 40
    assert all(q.gold for q in qs)


def test_holdout_law_mix():
    ho = load_questions(split="holdout")
    assert [q.law for q in ho].count("특허법") == 5
    assert [q.law for q in ho].count("시행령") == 2
    assert [q.law for q in ho].count("시행규칙") == 1


def test_h7_has_two_accepted_gold():
    h7 = next(q for q in load_questions() if q.id == "H7")
    assert set(h7.gold) == {"시행령#제9조", "특허법#제61조"}


def test_no_question_contains_article_number():
    assert all("제" not in q.question or "조" not in q.question.split("제")[-1][:3]
               for q in load_questions())


def test_dev_and_holdout_do_not_share_gold_article():
    dev = {g for q in load_questions(split="dev") for g in q.gold}
    ho = {g for q in load_questions(split="holdout") for g in q.gold}
    assert dev.isdisjoint(ho)


@pytest.mark.skipif(not CHUNKS.exists(), reason="청크 파일 없음(gitignore 대상)")
def test_patent_law_gold_exists_in_corpus():
    ids = {json.loads(l)["chunk_id"] for l in CHUNKS.read_text(encoding="utf-8").splitlines()}
    for q in load_questions():
        for g in q.gold:
            if g.startswith("특허법#"):
                assert g in ids, (q.id, g)


def test_corpus_gold_maps_short_law_names_and_keeps_full_names():
    from src.eval.questions import corpus_gold, corpus_law
    assert corpus_gold(("시행령#제9조", "특허법#제61조")) == ("특허법 시행령#제9조", "특허법#제61조")
    assert corpus_gold(("시행규칙#제16조",)) == ("특허법 시행규칙#제16조",)
    assert corpus_gold(("특허법 시행령#제9조",)) == ("특허법 시행령#제9조",)
    assert corpus_law("시행령") == "특허법 시행령" and corpus_law("특허법") == "특허법"
