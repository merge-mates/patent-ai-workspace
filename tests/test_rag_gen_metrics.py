from src.rag.gen_metrics import summarize_answerable, summarize_noanswer

CLEAN = {"unknown_tags": [], "articles_outside_evidence": [], "numbers_not_in_evidence": [],
         "status_cited_mismatch": False}


def row(i, status, cited_articles, gold=("특허법#제29조",), checks=None):
    return {"id": i, "gold": list(gold), "result": {"status": status, "cited_articles": cited_articles,
                                                     "checks": checks or CLEAN}}


def test_summarize_answerable_counts():
    rows = [row("a", "answered", ["특허법#제29조"]),
            row("b", "partial", ["특허법#제30조"]),
            row("c", "no_basis", []),
            row("d", "answered", ["특허법#제29조"], checks={**CLEAN, "numbers_not_in_evidence": ["12"]}),
            row("e", "error", [])]
    s = summarize_answerable(rows)
    assert (s["n"], s["cited_gold"], s["answered"], s["partial"], s["no_basis"], s["error"]) == (5, 2, 2, 1, 1, 1)
    assert s["check_failures"] == 1 and s["by_check"]["numbers_not_in_evidence"] == 1
    assert s["by_check"]["unknown_tags"] == 0


def test_cited_gold_counts_any_gold_article():
    rows = [row("a", "answered", ["시행령#x", "특허법#제30조"], gold=("특허법#제29조", "특허법#제30조"))]
    assert summarize_answerable(rows)["cited_gold"] == 1


def test_summarize_noanswer_lists_fabricated_ids():
    rows = [row("A", "no_basis", [], gold=()), row("B", "answered", ["x"], gold=()),
            row("C", "partial", [], gold=()), row("D", "error", [], gold=())]
    s = summarize_noanswer(rows)
    assert (s["n"], s["no_basis"], s["fabricated"], s["error"]) == (4, 1, 2, 1)
    assert s["fabricated_ids"] == ["B", "C"]
    assert (s["answered"], s["partial"]) == (1, 1)  # '답을 만듦' 안에서 answered 와 partial 을 나눠 본다


def test_cited_gold_counts_only_answered_or_partial_statuses():
    rows = [row("a", "no_basis", ["특허법#제29조"]),   # 근거 없음이라 했는데 인용이 남은 경우는 적중이 아니다
            row("b", "answered", ["특허법#제29조"]), row("c", "partial", ["특허법#제29조"]), row("d", "error", ["특허법#제29조"])]
    assert summarize_answerable(rows)["cited_gold"] == 2


def test_plain_style_detection_on_real_sentence_endings():
    from src.rag.gen_metrics import is_mostly_plain_style
    plain = ("**원칙적으로 다른 공유자 모두의 동의를 받아야만 지분을 양도할 수 있다.**\n"
             "- 특허법 제99조제2항: 특허권이 공유인 경우 동의를 받아야만 그 지분을 양도할 수 있다 (특허법 제99조).\n"
             "- 따라서 동의 없이 자기 지분만 임의로 팔 수는 없다.")
    polite = ("**동의를 받아야 지분을 양도할 수 있습니다.**\n- 공유자 모두의 동의가 필요합니다(특허법 제99조).\n"
              "- 따라서 임의로 팔 수 없어요.")
    assert is_mostly_plain_style(plain) is True and is_mostly_plain_style(polite) is False
    assert is_mostly_plain_style("") is False and is_mostly_plain_style("**근거로 확인되는 부분**") is False


def test_summarize_answerable_counts_plain_style_answers():
    plain = row("a", "answered", ["특허법#제29조"])
    plain["result"]["answer"] = "신규성이 없으면 특허를 받을 수 없다.\n그러나 예외가 있다."
    polite = row("b", "answered", ["특허법#제29조"])
    polite["result"]["answer"] = "신규성이 없으면 특허를 받을 수 없습니다."
    assert summarize_answerable([plain, polite])["plain_style"] == 1
