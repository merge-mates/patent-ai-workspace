import json
from pathlib import Path

import pytest

from src.rag.articles import get_article, load_articles


def corpus(tmp_path):
    rows = [{"chunk_id": "특허법#제30조",
             "text": "특허법 제30조(공지 등이 되지 아니한 발명으로 보는 경우)\n① 그 날부터 12개월 이내에 출원하면 <개정 2014.6.11, 2025.10.1>\n② 증명서류를 제출하여야 한다. <개정 2014.6.11>",
             "metadata": {"law_name": "특허법", "law_mst": "279827", "law_effective_date": "20251111", "label": "제30조",
                          "title": "공지 등이 되지 아니한 발명으로 보는 경우", "chapter": "제3장 특허출원 및 심사"}},
            {"chunk_id": "특허법 시행령#제5조", "text": "특허법 시행령 제5조(청구범위의 기재방법)\n본문",
             "metadata": {"law_name": "특허법 시행령", "law_mst": "277553", "law_effective_date": "20251001", "label": "제5조",
                          "title": "청구범위의 기재방법", "chapter": None}}]
    p = tmp_path / "a.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return p


def test_get_article_returns_text_and_source_and_hides_amendment_marks(tmp_path):
    arts = load_articles(corpus(tmp_path))
    a = get_article(arts, "특허법#제30조")
    assert a["article_id"] == "특허법#제30조" and a["label"] == "특허법 제30조" and a["law_name"] == "특허법"
    assert a["title"] == "공지 등이 되지 아니한 발명으로 보는 경우" and a["chapter"] == "제3장 특허출원 및 심사"
    assert a["source"] == "특허법 (시행 2025-11-11, 판본 279827)"
    assert "<개정" not in a["text"] and "12개월 이내에 출원하면" in a["text"] and "② 증명서류를 제출하여야 한다." in a["text"]


def test_get_article_can_keep_amendment_marks_and_handles_missing_chapter(tmp_path):
    arts = load_articles(corpus(tmp_path))
    assert "<개정 2014.6.11, 2025.10.1>" in get_article(arts, "특허법#제30조", hide_amendments=False)["text"]
    d = get_article(arts, "특허법 시행령#제5조")
    assert d["chapter"] is None and d["label"] == "특허법 시행령 제5조" and d["source"] == "특허법 시행령 (시행 2025-10-01, 판본 277553)"


def test_unknown_article_returns_none(tmp_path):
    assert get_article(load_articles(corpus(tmp_path)), "특허법#제9999조") is None


REAL = Path("data/processed/chunks_법령3_article.jsonl")


@pytest.mark.skipif(not REAL.exists(), reason="조문 청크 파일 없음(gitignore 대상)")
def test_real_corpus_has_all_cited_article_ids():
    arts = load_articles(REAL)
    assert len(arts) == 502 and get_article(arts, "특허법#제29조")["text"].startswith("특허법 제29조")
