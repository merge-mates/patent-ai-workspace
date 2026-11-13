from src.rag.evidence import Evidence
from src.rag.verify import check_answer


def ev(tag, article_id, text="본문"):
    return Evidence(tag=tag, article_id=article_id, label=article_id.replace("#", " "), text=text, truncated=False)


def test_unknown_tag_is_reported():
    r = check_answer("answered", "답", ["E1", "E9"], [ev("E1", "특허법#제30조"), ev("E2", "특허법#제29조")])
    assert r["unknown_tags"] == ["E9"]


def test_article_mention_outside_evidence():
    r = check_answer("answered", "제30조와 제47조의2에 따른다", ["E1"], [ev("E1", "특허법#제30조")])
    assert r["articles_outside_evidence"] == ["제47조의2"]


def test_number_not_in_evidence_ignores_article_and_paragraph_numbers():
    evidence = [ev("E1", "특허법#제29조", "출원일부터 3개월 이내")]
    r = check_answer("answered", "3개월 이내, 제29조 제2항, 12개월 [E1]", ["E1"], evidence)
    assert r["numbers_not_in_evidence"] == ["12"]


def test_status_cited_mismatch():
    e = [ev("E1", "특허법#제29조")]
    assert check_answer("no_basis", "근거 없음", ["E1"], e)["status_cited_mismatch"] is True
    assert check_answer("answered", "답", [], e)["status_cited_mismatch"] is True
    assert check_answer("partial", "답", [], e)["status_cited_mismatch"] is True
    assert check_answer("answered", "답", ["E1"], e)["status_cited_mismatch"] is False
    assert check_answer("no_basis", "근거 없음", [], e)["status_cited_mismatch"] is False


def test_clean_answer_has_empty_checks():
    e = [ev("E1", "특허법#제29조", "12개월 이내에 출원")]
    r = check_answer("answered", "12개월 이내에 출원해야 합니다(특허법 제29조) [E1]", ["E1"], e)
    assert r == {"unknown_tags": [], "articles_outside_evidence": [], "numbers_not_in_evidence": [],
                 "status_cited_mismatch": False}


def test_article_mentioned_inside_evidence_text_is_not_flagged():
    # 근거 조문 본문이 다른 조문을 인용하고 있으면(예: "제29조제1항") 답변이 그 조문을 말해도 근거 밖이 아니다
    e = [ev("E1", "특허법#제30조", "제29조제1항 적용 시 공지가 아닌 것으로 본다")]
    r = check_answer("answered", "제30조에 따르며 제29조제1항 적용 시 공지가 아닌 것으로 봅니다. 제99조도 있습니다", ["E1"], e)
    assert r["articles_outside_evidence"] == ["제99조"]


def test_error_status_does_not_count_as_status_cited_mismatch():
    # 파싱 실패(error)는 답이 없는 상태라 인용이 비어 있는 것이 당연하다: 검증 경고에 섞지 않는다
    assert check_answer("error", "", [], [ev("E1", "특허법#제29조")])["status_cited_mismatch"] is False


# ---- 작은 지적 정리(M3): 숫자·조문·꼬리표 인식 ----
def test_list_markers_and_thousands_separators_are_not_unsupported_numbers():
    e = [ev("E1", "특허법#제29조", "수수료는 1,000원이다. 12개월 이내")]
    r = check_answer("answered", "- 국제출원은 다음과 같습니다.\n5. 국제특허출원은 12개월입니다. 수수료 1,000원(E1)", ["E1"], e)
    assert r["numbers_not_in_evidence"] == []  # 목록 번호 "5."와 쉼표 숫자 "1,000"의 "000"을 오경보하지 않는다


def test_real_unsupported_number_next_to_list_markers_is_still_reported():
    e = [ev("E1", "특허법#제29조", "12개월 이내")]
    r = check_answer("answered", "1. 12개월 이내입니다.\n2. 수수료는 3,500원입니다.", ["E1"], e)
    assert r["numbers_not_in_evidence"] == ["3500"]


def test_dates_with_spaces_are_not_mistaken_for_list_markers():
    e = [ev("E1", "특허법#제29조", "시행일 2025. 10. 1.")]
    assert check_answer("answered", "2025. 10. 1. 부터입니다 [E1]", ["E1"], e)["numbers_not_in_evidence"] == []


def test_spaced_article_numbers_and_tags_with_korean_particles_are_recognized():
    e = [ev("E1", "특허법#제30조", "본문 3개월")]
    r = check_answer("answered", "E1에 따라 제 47 조와 제47조의2를 보며 3개월, 12개월", ["E1"], e)
    assert r["articles_outside_evidence"] == ["제47조", "제47조의2"]
    assert r["numbers_not_in_evidence"] == ["12"]  # "E1에", "제 47 조", "제47조의 2" 속 숫자는 수치가 아니다


def test_possessive_eui_before_a_counter_is_not_a_branch_article():
    # 실제 답변 "법 제61조의 3가지 유형"에서 "의"는 조사다(제61조의3 이 아님). "의" 뒤 띄어 쓴 숫자는 가지 번호로 읽지 않는다
    e = [ev("E1", "특허법#제61조", "우선심사")]
    r = check_answer("answered", "법 제61조의 3가지 유형이 있습니다 [E1]", ["E1"], e)
    assert r["articles_outside_evidence"] == []
