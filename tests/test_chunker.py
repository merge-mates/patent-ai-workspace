import hashlib
import json
from pathlib import Path
import pytest
from src.law_api.chunker import (
    build_chunks, load_law, main, normalize_article, parse_heading, strip_amend_tags,
)

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
LAW = RAW / "body_특허법_279827_20251111.json"
needs_data = pytest.mark.skipif(not LAW.exists(), reason="data/raw 파일 없음")

def unit(**kw):
    base = {"조문여부": "조문", "조문번호": "1", "조문키": "0001001",
            "조문시행일자": "20251111", "조문제목": "", "조문내용": ""}
    base.update(kw)
    return base

def by_label(law, label):
    return next(a for a in law.articles if a.label == label)

@pytest.fixture(scope="module")
def law():
    return load_law(LAW)

def test_label_with_branch():
    a = normalize_article(unit(조문번호="132", 조문가지번호="17", 조문제목="심판",
                               조문내용="제132조의17(심판) 본문입니다."))
    assert (a.label, a.number, a.branch, a.title) == ("제132조의17", 132, 17, "심판")
    assert a.lead == "본문입니다." and a.paragraphs == () and not a.deleted

def test_whole_article_deleted():
    a = normalize_article(unit(조문번호="26", 조문내용="제26조 삭제 <2011.12.2>"))
    assert a.deleted and a.title == "" and a.lead == "" and a.paragraphs == ()

def test_ho_only_paragraph_keeps_lead_and_items():
    a = normalize_article(unit(
        조문번호="2", 조문제목="정의",
        조문내용="제2조(정의) 용어의 뜻은 다음과 같다. <개정 2019.12.10>",
        항={"호": [{"호번호": "1.", "호내용": '1. "발명"이란 가.'},
                  {"호번호": "3.", "호내용": '3. "실시"란 다음과 같다.',
                   "목": [{"목번호": "가.", "목내용": "가. 물건의 발명인 경우"}]}]}))
    assert a.lead == "용어의 뜻은 다음과 같다. <개정 2019.12.10>"
    assert len(a.paragraphs) == 1 and a.paragraphs[0].number is None
    assert a.paragraphs[0].lines == ('1. "발명"이란 가.', '3. "실시"란 다음과 같다.', "가. 물건의 발명인 경우")

def test_single_dict_paragraph_with_content():
    a = normalize_article(unit(조문제목="가", 조문내용="제1조(가)",
                               항={"항번호": "①", "항내용": "① 본문"}))
    assert [(p.number, p.lines) for p in a.paragraphs] == [("①", ("① 본문",))]

def test_list_paragraphs_and_deleted_flag():
    a = normalize_article(unit(조문번호="42", 조문제목="특허출원", 조문내용="제42조(특허출원)",
                               항=[{"항번호": "④", "항내용": "④ 본문"},
                                  {"항번호": "⑤", "항내용": "⑤ 삭제 <2014.6.11>"}]))
    assert a.lead == ""
    assert [(p.number, p.deleted) for p in a.paragraphs] == [("④", False), ("⑤", True)]

@needs_data
def test_real_counts(law):
    assert (law.name, law.mst, law.effective_date) == ("특허법", "279827", "20251111")
    assert len(law.articles) == 298
    assert sum(a.deleted for a in law.articles) == 30
    assert len({a.label for a in law.articles}) == 298
    gone = [(a.label, p.number) for a in law.articles for p in a.paragraphs if p.deleted]
    assert len(gone) == 10 and len({lb for lb, _ in gone}) == 8
    assert [p.number for p in by_label(law, "제42조").paragraphs if p.deleted] == ["⑤", "⑦"]

@needs_data
def test_real_article_29(law):
    a = by_label(law, "제29조")
    assert a.title == "특허요건" and len(a.paragraphs) == 7
    assert a.paragraphs[0].lines[0].startswith("① 산업상 이용할 수 있는 발명으로서")
    assert len(a.paragraphs[0].lines) == 3


def heading(text, key="0001000"):
    return {"조문여부": "전문", "조문번호": "1", "조문키": key, "조문내용": "            " + text}

def write_law(tmp_path, units):
    p = tmp_path / "body_가법_1_20250101.json"
    p.write_text(json.dumps({"법령": {"기본정보": {"법령명_한글": "가법", "시행일자": "20250101"},
                                     "조문": {"조문단위": units}}}, ensure_ascii=False), encoding="utf-8")
    return p

def test_heading_levels_and_reset(tmp_path):
    units = [heading("제1장 총칙 <개정 2014.6.11>"), unit(조문번호="1", 조문키="0001001", 조문내용="제1조(가) 가."),
             heading("제2장 심사"), heading("제1절 가절"), heading("제1관 가관"),
             unit(조문번호="10", 조문키="0010001", 조문내용="제10조(나) 나."),
             heading("제2절 나절"), unit(조문번호="11", 조문키="0011001", 조문내용="제11조(다) 다."),
             heading("제3장의2 특수 <신설 2016.2.29>"), unit(조문번호="20", 조문키="0020001", 조문내용="제20조(라) 라.")]
    law = load_law(write_law(tmp_path, units))
    a1, a10, a11, a20 = law.articles
    assert (a1.chapter, a1.section, a1.subsection) == ("제1장 총칙", None, None)
    assert (a10.chapter, a10.section, a10.subsection) == ("제2장 심사", "제1절 가절", "제1관 가관")
    assert (a11.chapter, a11.section, a11.subsection) == ("제2장 심사", "제2절 나절", None)
    assert (a20.chapter, a20.section, a20.subsection) == ("제3장의2 특수", None, None)

def test_unknown_heading_raises(tmp_path):
    with pytest.raises(ValueError, match="제1편"):
        load_law(write_law(tmp_path, [heading("제1편 총칙"), unit(조문내용="제1조(가) 가.")]))

def test_parse_heading():
    assert parse_heading("   제6장의2 특허취소신청 <신설 2016.2.29>") == ("chapter", "제6장의2 특허취소신청")

@needs_data
def test_real_chapters(law):
    want = {"제1조": ("제1장 총칙", None), "제29조": ("제2장 특허요건 및 특허출원", None),
            "제132조의2": ("제6장의2 특허취소신청", None), "제132조의17": ("제7장 심판", None),
            "제199조": ("제10장 「특허협력조약」에 따른 국제출원", "제2절 국제특허출원에 관한 특례"),
            "제215조": ("제11장 보칙", None)}
    for label, (chap, sec) in want.items():
        a = by_label(law, label)
        assert (a.chapter, a.section) == (chap, sec), label
    assert len(law.articles) == 298  # 전문(장 제목)은 조문으로 세지 않는다

@pytest.mark.parametrize("name,n_articles", [("body_특허법_시행령_277553_20251001.json", 27),
                                              ("body_특허법_시행규칙_286191_20260514.json", 236)])
def test_other_laws_load(name, n_articles):
    path = RAW / name
    if not path.exists():
        pytest.skip("data/raw 파일 없음")
    law = load_law(path)
    assert len(law.articles) == n_articles
    if "시행령" in name:
        assert by_label(law, "제1조").chapter == "제1장 총칙 및 특허출원"
    else:
        assert any(a.subsection for a in law.articles)


# ---- Task 3: 청크 생성 ----

@pytest.fixture(scope="module")
def chunks(law):
    return build_chunks(law)

def chunk_of(chunks, label):
    return next(c for c in chunks if c.chunk_id == f"특허법#{label}")

def test_strip_amend_tags_keeps_dateless_brackets():
    assert strip_amend_tags("<별표 1> 참조 <개정 2014.6.11>") == "<별표 1> 참조"

@needs_data
def test_unknown_strategy_raises(law):
    with pytest.raises(ValueError):
        build_chunks(law, strategy="sentence")

@needs_data
def test_chunk_count_and_ids(chunks):
    assert len(chunks) == 268 and len({c.chunk_id for c in chunks}) == 268
    assert chunks[0].chunk_id == "특허법#제1조"
    assert all(len(c.text.splitlines()) >= 2 for c in chunks)  # 이름표만 있는 빈 청크 없음

@needs_data
def test_article_1_exact_text(chunks):
    assert chunk_of(chunks, "제1조").text == (
        "특허법 제1조(목적)\n이 법은 발명을 보호ㆍ장려하고 그 이용을 도모함으로써 기술의 발전을 촉진하여 산업발전에 이바지함을 목적으로 한다.")

@needs_data
def test_article_29_structure(chunks):
    t = chunk_of(chunks, "제29조").text
    lines = t.splitlines()
    assert lines[0] == "특허법 제29조(특허요건)"
    assert lines[1].startswith("① 산업상 이용할 수 있는 발명으로서")
    assert t.index("① ") < t.index("1. 특허출원 전에") < t.index("② ")

@needs_data
def test_article_2_lead_and_tags(law):
    on = chunk_of(build_chunks(law), "제2조").text.splitlines()
    off = chunk_of(build_chunks(law, strip_tags=True), "제2조").text.splitlines()
    assert on[1] == "이 법에서 사용하는 용어의 뜻은 다음과 같다. <개정 2019.12.10, 2025.1.21>"
    assert off[1] == "이 법에서 사용하는 용어의 뜻은 다음과 같다."
    assert any(l.startswith("가. 물건의 발명인 경우") for l in on)

@needs_data
def test_article_42_skips_deleted_paragraphs(chunks):
    t = chunk_of(chunks, "제42조").text
    assert "⑤ 삭제" not in t and "⑦ 삭제" not in t and "④ " in t

@needs_data
def test_strip_tags_removes_all_dated_tags(law):
    import re
    tag = re.compile(r"<[^<>]*\d{4}\.\d{1,2}\.\d{1,2}[^<>]*>")
    assert not any(tag.search(c.text) for c in build_chunks(law, strip_tags=True))

@needs_data
def test_metadata_article_132_17(chunks):
    m = chunk_of(chunks, "제132조의17").metadata
    assert m == {"law_name": "특허법", "law_mst": "279827", "law_effective_date": "20251111",
                 "label": "제132조의17", "article_no": 132, "branch_no": 17,
                 "title": "특허거절결정 등에 대한 심판", "chapter": "제7장 심판", "section": None,
                 "subsection": None, "source_key": "0132171",
                 "char_len": len(chunk_of(chunks, "제132조의17").text), "strategy": "article"}


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

@needs_data
def test_cli_writes_deterministic_jsonl(tmp_path, capsys):
    before = sha(LAW)
    assert main([str(LAW), "--out-dir", str(tmp_path)]) == 0
    out = tmp_path / "chunks_특허법_279827_20251111.jsonl"
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 268 and len({r["chunk_id"] for r in rows}) == 268
    assert set(rows[0]) == {"chunk_id", "text", "metadata"}
    assert "268" in capsys.readouterr().out
    first = out.read_bytes()
    assert main([str(LAW), "--out-dir", str(tmp_path)]) == 0
    assert out.read_bytes() == first
    assert sha(LAW) == before  # 원본 불변

@needs_data
def test_cli_strip_tags_filename(tmp_path):
    assert main([str(LAW), "--out-dir", str(tmp_path), "--strip-tags"]) == 0
    assert (tmp_path / "chunks_특허법_279827_20251111_notags.jsonl").exists()

@needs_data
def test_cli_refuses_raw_dir():
    assert main([str(LAW), "--out-dir", str(RAW)]) == 2
    assert not list(RAW.glob("chunks_*"))

@needs_data
def test_eval_answer_articles_present_in_expected_chapter(chunks):
    expected = {"제29조": "제2장", "제36조": "제2장", "제63조": "제3장", "제47조": "제2장",
                "제52조": "제2장", "제132조의17": "제7장", "제133조": "제7장", "제136조": "제7장",
                "제55조": "제2장", "제32조": "제2장", "제42조": "제2장"}
    for label, chap in expected.items():
        assert chunk_of(chunks, label).metadata["chapter"].startswith(chap + " "), label


# ---- 최종 리뷰 수정 ----
def test_list_valued_mok_content_flattened():
    art = normalize_article(unit(조문번호="7", 조문내용="제7조(가) 가.", 항=[{"항내용": "①가.", "호": [
        {"호내용": "1. 호", "목": [{"목내용": [["저. 첫째", " "], "  둘째  ", [[""]]]}]}]}]))
    assert art.paragraphs[0].lines == ("①가.", "1. 호", "저. 첫째", "둘째")

def test_non_str_non_list_content_raises():
    with pytest.raises(TypeError):
        normalize_article(unit(조문내용="제1조(가) 가.", 항=[{"항내용": 5}]))

LAW_FILES = ["body_특허법_279827_20251111.json", "body_특허법_시행령_277553_20251001.json",
             "body_특허법_시행규칙_286191_20260514.json"]

@pytest.mark.parametrize("strip_tags", [False, True])
@pytest.mark.parametrize("name", LAW_FILES)
def test_real_laws_chunk_invariants(name, strip_tags):
    path = RAW / name
    if not path.exists():
        pytest.skip("data/raw 파일 없음")
    chunks = build_chunks(load_law(path), strip_tags=strip_tags)
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))
    for c in chunks:
        lines = c.text.split("\n")
        assert len(lines) >= 2, c.chunk_id
        assert all(l.strip() for l in lines), c.chunk_id
        assert "['" not in c.text and "None" not in c.text, c.chunk_id

def test_strip_tags_drops_tag_only_lines(tmp_path):
    units = [unit(조문번호="1", 조문제목="가", 조문내용="제1조(가) <개정 2014.6.11>", 항=[
        {"항내용": "①본문", "호": [{"호내용": "<개정 2014.6.11>"}]}])]
    law = load_law(write_law(tmp_path, units))
    text = build_chunks(law, strip_tags=True)[0].text
    assert text == "가법 제1조(가)\n①본문"

def test_null_jomun_via_main(tmp_path):
    p = tmp_path / "in" / "body_가법_1_20250101.json"
    p.parent.mkdir()
    p.write_text(json.dumps({"법령": {"기본정보": {"법령명_한글": "가법", "시행일자": "20250101"},
                                     "조문": None}}), encoding="utf-8")
    # 조문이 null이면 조문 0개 -> 청크 0개로 정상 종료(0)
    assert main([str(p), "--out-dir", str(tmp_path / "out")]) == 0

def test_malformed_type_returns_1(tmp_path, capsys):
    p = tmp_path / "in" / "body_가법_1_20250101.json"
    p.parent.mkdir()
    p.write_text(json.dumps({"법령": {"기본정보": {"법령명_한글": "가법", "시행일자": "20250101"},
                                     "조문": "x"}}), encoding="utf-8")
    assert main([str(p), "--out-dir", str(tmp_path / "out")]) == 1
    assert "오류" in capsys.readouterr().err

def test_parse_heading_multiple_trailing_tags():
    assert parse_heading("제1장 총칙 <개정 2014.6.11> <신설 2016.2.29>") == ("chapter", "제1장 총칙")


# ---- Task 5: 삭제된 호·목 줄 제외 ----
from src.law_api.chunker import _PARAGRAPH_DELETED_RE, _flatten


def test_deleted_ho_mok_excluded_numbers_not_renumbered():
    a = normalize_article(unit(조문번호="9", 조문제목="가", 조문내용="제9조(가)", 항=[{"항내용": "①본문", "호": [
        {"호내용": "2. 둘째"},
        {"호내용": "3. 삭제 <2017.3.21>"},
        {"호내용": "4. 넷째", "목": [
            {"목내용": "가. 삭제 <2017.3.21>"},
            {"목내용": "나. 남는 목"},
            {"목내용": "다. 삭제<2017.3.21>"}]},
        {"호내용": "5. 삭제<2017.3.21>"}]}]))
    assert a.paragraphs[0].lines == ("①본문", "2. 둘째", "4. 넷째", "나. 남는 목")

def test_normal_line_containing_deleted_word_kept():
    a = normalize_article(unit(조문번호="47", 조문제목="가", 조문내용="제47조(가)", 항=[{"항내용": "①본문", "호": [
        {"호내용": "1. 청구범위를 한정 또는 삭제하거나 정정하는 경우"},
        {"호내용": "2. x", "목": [{"목내용": "다. 국제출원에서 삭제된 청구항의 번호"}]}]}]))
    assert len(a.paragraphs[0].lines) == 4

def test_paragraph_with_only_deleted_items_dropped_from_chunk():
    from src.law_api.chunker import Law
    a = normalize_article(unit(조문번호="9", 조문제목="가", 조문내용="제9조(가) 본문", 항=[
        {"항번호": "①", "호": [{"호내용": "1. 삭제 <2017.3.21>"}, {"호내용": "2. 삭제 <2017.3.21>"}]}]))
    assert a.paragraphs[0].lines == ()
    c = build_chunks(Law("테스트법", "1", "20250101", (a,)))[0]
    assert c.text == "테스트법 제9조(가)\n본문"

def _raw_deleted_count(path):
    data = json.loads(path.read_text(encoding="utf-8"))["법령"]
    n = 0
    for u in (data.get("조문") or {}).get("조문단위") or []:
        paras = u.get("항") or []
        for p in (paras if isinstance(paras, list) else [paras]):
            hos = p.get("호") or []
            for ho in (hos if isinstance(hos, list) else [hos]):
                lines = _flatten(ho.get("호내용"))
                moks = ho.get("목") or []
                for mok in (moks if isinstance(moks, list) else [moks]):
                    lines += _flatten(mok.get("목내용"))
                n += sum(1 for l in lines if _PARAGRAPH_DELETED_RE.match(l))
    return n

@pytest.mark.parametrize("strip_tags", [False, True])
@pytest.mark.parametrize("name,excluded,n_chunks", [
    (LAW_FILES[0], 2, 268), (LAW_FILES[1], 4, 25), (LAW_FILES[2], 23, 209)])
def test_real_deleted_lines_excluded(name, excluded, n_chunks, strip_tags):
    path = RAW / name
    if not path.exists():
        pytest.skip("data/raw 파일 없음")
    law_ = load_law(path)
    chunks_ = build_chunks(law_, strip_tags=strip_tags)
    assert len(chunks_) == n_chunks
    for c in chunks_:
        for l in c.text.split("\n")[1:]:
            assert not _PARAGRAPH_DELETED_RE.match(l), (c.chunk_id, l)
    # 법령 객체에서 호·목 줄이 빠졌는지: 원본 삭제 줄 수가 기대값과 같고, 제외 전후 줄 수 차이와 일치
    assert _raw_deleted_count(path) == excluded

@needs_data
def test_real_patent_act_deleted_and_kept_lines(chunks):
    assert "나. 삭제" not in chunk_of(chunks, "제84조").text
    assert "3. 삭제" not in chunk_of(chunks, "제223조").text
    assert "청구항을 한정 또는 삭제하거나" in chunk_of(chunks, "제47조").text
