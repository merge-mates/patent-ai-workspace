from src.law_api.chunker import Article, Law, Paragraph, build_chunks, _output_name
from pathlib import Path


def art(paragraphs, label="제7조의2", title="지연", lead=""):
    return Article(label=label, number=7, branch=2, title=title, lead=lead, paragraphs=tuple(paragraphs),
                   deleted=False, source_key="k", effective_date="20251001")


def law_of(*a):
    return Law(name="특허법 시행령", mst="1", effective_date="20251001", articles=tuple(a))


def long_para():
    lines = ["① 기간이란 다음 각 호의 기간을 말한다."]
    for n in range(1, 7):
        lines.append(f"{n}. " + "가" * 100)
        lines.append("가. " + "나" * 100)  # 목은 앞의 호에 붙는다
    return Paragraph(number="①", lines=tuple(lines), deleted=False)


def test_long_chunk_is_split_at_ho_boundaries_with_prefix_repeated():
    law = law_of(art([long_para(), Paragraph(number="②", lines=("② 짧다",), deleted=False)]))
    ch = build_chunks(law, strategy="paragraph", max_chars=500)
    ids = [c.chunk_id for c in ch]
    assert ids[-1] == "특허법 시행령#제7조의2#제2항"
    parts = [c for c in ch if c.chunk_id.startswith("특허법 시행령#제7조의2#제1항#")]
    assert len(parts) >= 2 and [p.chunk_id.rsplit("#", 1)[1] for p in parts] == [str(i) for i in range(1, len(parts) + 1)]
    for p in parts:
        assert p.text.startswith("특허법 시행령 제7조의2(지연)\n① 기간이란")
        assert p.metadata["parts"] == len(parts) and p.metadata["part"] == int(p.chunk_id.rsplit("#", 1)[1])
    # 호가 빠지거나 중복되지 않고, 각 호는 자기 목과 같은 조각에 있다
    body = "\n".join(p.text for p in parts)
    for n in range(1, 7):
        assert body.count(f"\n{n}. ") == 1
    for p in parts:
        lines = p.text.split("\n")
        for i, ln in enumerate(lines):
            if ln.startswith("가. "):
                assert lines[i - 1][:2].rstrip(".").isdigit()


def test_short_chunks_and_none_max_chars_are_unchanged():
    law = law_of(art([long_para(), Paragraph(number="②", lines=("② 짧다",), deleted=False)]))
    assert [c.chunk_id for c in build_chunks(law, strategy="paragraph")] == [
        "특허법 시행령#제7조의2#제1항", "특허법 시행령#제7조의2#제2항"]
    assert [c.chunk_id for c in build_chunks(law, strategy="paragraph", max_chars=100000)] == [
        "특허법 시행령#제7조의2#제1항", "특허법 시행령#제7조의2#제2항"]


def test_chunk_without_ho_lines_is_not_split_even_if_long():
    p = Paragraph(number="①", lines=("① " + "가" * 2000,), deleted=False)
    law = law_of(art([p, Paragraph(number="②", lines=("② 둘",), deleted=False)]))
    assert len(build_chunks(law, strategy="paragraph", max_chars=500)) == 2


def test_output_name_has_split_suffix():
    assert _output_name(Path("body_x_1_20251001.json"), False, "paragraph", 3000).endswith("_paragraph_split3000.jsonl")
    assert _output_name(Path("body_x_1_20251001.json"), False, "paragraph") .endswith("_paragraph.jsonl")
