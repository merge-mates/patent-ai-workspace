"""미국 공개공보 청킹. 글자는 모두 지어낸 영어 문장."""

import pytest

from patent_ai.retrieval.cite_index import PageText
from patent_ai.retrieval.cite_index.chunker import (
    chunk_document,
    chunk_document_checked,
    longest_increasing,
    parse_us_figures,
    us_paragraph_number,
)

IV = "cite-idx-v1"
DOC = "US20130000001A1"


def _keys(chunks):
    return [c.chunk_id.split(":", 2)[2] for c in chunks]


def _by_key(chunks):
    return {c.chunk_id.split(":", 2)[2]: c for c in chunks}


# --- 문단 번호 한 줄 읽기 ---


@pytest.mark.parametrize(
    "line, expected",
    [
        ("0025 Referring to the made up part", (25, "Referring to the made up part")),
        ("0001. This is made up", (1, "This is made up")),
        ("[0025] The widget", (25, "The widget")),
        ("[0 025 ] This is fake", (25, "This is fake")),  # 숫자 사이 공백
        ("10025 ] This is fake", (25, "This is fake")),  # [ 를 1로 읽음
        ("I0026. The part", (26, "The part")),  # [ 를 I로 읽음
        ("(0027 First part", (27, "First part")),  # 닫는 괄호 없음
        ("[O025] Zero as letter", (25, "Zero as letter")),  # 0을 O로 읽음
    ],
)
def test_문단_번호_여러_꼴을_읽는다(line, expected):
    assert us_paragraph_number(line) == expected


@pytest.mark.parametrize(
    "line",
    ["The widget is made", "[025] three digits", "12345 five digits here", "[0000] zero", ""],
)
def test_문단_번호가_아닌_줄은_None(line):
    assert us_paragraph_number(line) is None


def test_앞쪽_글자가_없는_네_자리_수도_일단_후보로_읽는다():
    # 표지의 연도·번호도 후보가 된다. 걸러내는 건 longest_increasing
    assert us_paragraph_number("4321 widgets were sold") == (4321, "widgets were sold")


# --- 늘어나는 번호만 남기기 ---


def test_longest_increasing_앞의_튀는_번호와_역순을_버린다():
    nums = [4321, 1, 2, 3, 7, 4, 5]
    assert longest_increasing(nums) == [1, 2, 3, 5, 6]  # 1·2·3·4·5의 자리


def test_longest_increasing_같은_수는_버리고_빈_목록은_빈_목록():
    assert longest_increasing([]) == []
    assert longest_increasing([1, 1, 2]) == [1, 2]  # 같은 길이면 뒤의 1을 남긴다


# --- 도면 번호 ---


@pytest.mark.parametrize(
    "text, expected",
    [
        ("shown in FIG. 3", [3]),
        ("see FIG. 3A", [3]),
        ("FIGS. 3 and 4", [3, 4]),
        ("FIGS. 3-5", [3, 4, 5]),
        ("FIGS. 3 to 5", [3, 4, 5]),
        ("FIGS. 3 through 5", [3, 4, 5]),
        ("FIGS. 3A-3C", [3]),
        ("FIG. 2 and FIG. 2 again, FIG. 4", [2, 4]),
        ("no drawing here", []),
    ],
)
def test_미국_도면_번호(text, expected):
    assert parse_us_figures(text) == expected


# --- 문헌 하나 ---


def _a1_pages():
    return [
        PageText(
            page=1,
            lines=[
                "(21) Appl. No.: 13/000,000",
                "4321 widgets were sold",
                "",
                "(57) ABSTRACT",
                "A made up widget has a body.",
                "Shown in FIG. 2 and FIG. 4.",
                "",
                "junk label",
            ],
        ),
        PageText(
            page=2,
            lines=[
                "BACKGROUND",
                "text before first marker",
                "[0001] The widget is made up.",
                "0002 See FIG. 2 and FIGS. 3-5 for",
                "details of it.",
                "SUMMARY",
                "0004. Another part.",
            ],
        ),
        PageText(
            page=3,
            lines=[
                "What is claimed is:",
                "1. A widget comprising",
                "a body; and",
                "2. The widget of claim 1, wherein the body is round.",
            ],
        ),
    ]


def test_공개공보_조각_키와_종류():
    chunks, _ = chunk_document(DOC, _a1_pages(), IV)
    assert _keys(chunks) == ["abs", "p0001", "p0002", "p0004", "claim1", "claim2"]
    c = _by_key(chunks)
    assert c["abs"].chunk_kind == "abstract"
    assert c["p0001"].chunk_kind == "body"
    assert c["claim1"].chunk_kind == "claim"
    assert c["p0001"].chunk_id == f"{IV}:{DOC}:p0001"
    assert all(x.edition.status == "not_applicable" for x in chunks)


def test_공개공보_위치와_글자():
    c = _by_key(chunk_document(DOC, _a1_pages(), IV)[0])
    assert c["abs"].text == "A made up widget has a body. Shown in FIG. 2 and FIG. 4."
    assert (c["abs"].location.kind, c["abs"].location.label) == ("abstract", "요약")
    assert c["abs"].location.figures == [2, 4]
    loc = c["p0002"].location
    assert (loc.kind, loc.start, loc.end, loc.label) == ("paragraph", 2, 2, "[0002]")
    assert loc.figures == [2, 3, 4, 5]
    assert c["p0002"].text == "See FIG. 2 and FIGS. 3-5 for details of it."  # 제목 줄은 안 붙음
    assert c["p0004"].text == "Another part."
    assert c["claim1"].text == "A widget comprising a body; and"
    assert c["claim2"].location.claims == [2]
    assert c["claim2"].location.label == "청구항 2"


def test_번호_빠짐은_경고하고_표지_숫자는_경고없이_센다():
    chunks, warns, check = chunk_document_checked(DOC, _a1_pages(), IV)
    assert warns == [f"문단 번호 빠짐: {DOC} 1개 (1~4)"]  # 4321은 첫 문단 앞이라 경고 없음
    assert check == {
        "last": 4,
        "accepted": 3,
        "missing": 1,
        "out_of_order": 0,
        "skipped_before_first": 1,
        "after_last": 0,
        "dropped_lines": 0,
    }
    assert chunks  # chunk_document와 같은 조각


def test_chunk_document는_두_값만_돌려준다():
    out = chunk_document(DOC, _a1_pages(), IV)
    assert len(out) == 2


def test_청구항_머리가_없어도_1_로_시작하면_청구항():
    pages = [
        PageText(
            page=1,
            lines=[
                "[0001] First part.",
                "[0002] Second part.",
                "1. An apparatus comprising a part.",
                "2. The apparatus of claim 1.",
            ],
        )
    ]
    chunks, warns, check = chunk_document_checked(DOC, pages, IV)
    assert _keys(chunks) == ["p0001", "p0002", "claim1", "claim2"]
    assert _by_key(chunks)["p0002"].text == "Second part."  # 청구항 글자가 문단에 안 섞임
    assert warns == [f"요약 없음: {DOC}"] and check["missing"] == 0 and check["out_of_order"] == 0


def test_청구항을_못_찾으면_경고():
    pages = [PageText(page=1, lines=["[0001] First part.", "[0002] Second part."])]
    _, warns = chunk_document(DOC, pages, IV)
    assert f"청구항 시작 못 찾음: {DOC}" in warns


def test_청구항_번호가_건너뛰면_앞_청구항에_이어_붙인다():
    pages = [
        PageText(
            page=1,
            lines=["[0001] A.", "We claim:", "1. A thing.", "5. stray line", "2. The thing."],
        )
    ]
    c = _by_key(chunk_document(DOC, pages, IV)[0])
    assert c["claim1"].text == "A thing. 5. stray line"
    assert c["claim2"].text == "The thing."


def test_문단_번호가_하나도_없으면_본문_조각_없음():
    pages = [PageText(page=1, lines=["1. A thing.", "2. The thing."])]
    chunks, warns, check = chunk_document_checked(DOC, pages, IV)
    assert "문단 번호 없음: 본문 조각 안 만듦" in warns
    assert not [c for c in chunks if c.chunk_kind == "body"]
    assert check["last"] is None and check["accepted"] == 0
    assert not [c for c in chunks if c.chunk_kind == "claim"]  # 문단 번호가 없으면 청구항도 안 만듦


def test_같은_문단_번호가_두_번이면_앞의_것만_남긴다():
    pages = [
        PageText(
            page=1, lines=["[0001] first.", "[0002] second.", "[0001] again.", "[0003] third."]
        )
    ]
    chunks, warns, check = chunk_document_checked(DOC, pages, IV)
    assert _keys(chunks) == ["p0001", "p0002", "p0003"]
    assert _by_key(chunks)["p0001"].text == "first."
    assert f"문단 번호 역순·튐 무시: {DOC} 1개 (본문 글자로 둠)" in warns
    assert check["out_of_order"] == 1


def test_등록공보는_아직_지원_안_함():
    chunks, warns = chunk_document("US7654321B2", _a1_pages(), IV)
    assert chunks == []
    assert any("지원 안 함" in w for w in warns)
    chunks, check_warns, check = chunk_document_checked("US7654321B2", _a1_pages(), IV)
    assert check is None


def _run(lines):
    chunks, warns, check = chunk_document_checked(DOC, [PageText(page=1, lines=lines)], IV)
    return chunks, warns, check


def test_문단_가운데_대문자_줄은_제목이_아니라_본문():
    lines = [
        "[0001] Memory may be",
        "SRAM, DRAM, ROM,",
        "or flash memory in this part.",
        "[0002] Second.",
        "1. A widget.",
    ]
    c = _by_key(_run(lines)[0])
    assert c["p0001"].text == "Memory may be SRAM, DRAM, ROM, or flash memory in this part."


def test_다음_문단_앞의_대문자_줄은_제목이라_버리고_청구항_앞도_제목():
    lines = ["[0001] A.", "SUMMARY", "[0002] B.", "CLAIMS HERE", "1. A widget."]
    chunks, _, check = _run(lines)
    c = _by_key(chunks)
    assert c["p0001"].text == "A." and c["p0002"].text == "B."
    assert check["dropped_lines"] == 0


def test_어느_조각에도_못_든_줄은_세고_경고한다():
    lines = ["[0001] A.", "What is claimed is:", "stray junk line", "1. A widget."]
    _, warns, check = _run(lines)
    assert check["dropped_lines"] == 1
    assert f"버린 줄: {DOC} 1개" in warns


def test_번호_점프_제한_뒤에_큰_번호가_끼어도_진짜_문단이_남는다():
    # (a) 1102는 번호 점프가 커서 문단이 아님. 진짜 [0005]가 밀려나면 안 된다
    lines = ["[0001] a.", "[0002] b.", "[0003] c.", "[0004] d.", "1102 is coupled to a bus.",
             "[0005] e.", "1. A widget."]  # fmt: skip
    chunks, _, check = _run(lines)
    assert _keys(chunks)[:5] == ["p0001", "p0002", "p0003", "p0004", "p0005"]
    assert "p1102" not in _keys(chunks)
    assert _by_key(chunks)["p0004"].text == "d. 1102 is coupled to a bus."


def test_마지막_문단_뒤의_큰_수는_청구항을_삼키지_않는다():
    # (b) "1000 degrees C." 가 문단 번호로 읽히면 청구항 1이 그 문단에 들어간다
    lines = ["[0001] a.", "[0002] b.", "1000 degrees C. is hot.", "1. A widget.", "2. The widget."]
    chunks, _, _ = _run(lines)
    assert "p1000" not in _keys(chunks)
    assert _keys(chunks) == ["p0001", "p0002", "claim1", "claim2"]
    assert _by_key(chunks)["p0002"].text == "b. 1000 degrees C. is hot."


def test_청구항_머리_뒤의_번호_같은_줄은_문단_후보가_아니다():
    # (c) 청구항 글자 속 "2008 the widget…"
    lines = ["[0001] a.", "[0002] b.", "We claim:", "1. A widget", "2008 the widget is round."]
    chunks, _, _ = _run(lines)
    assert _keys(chunks) == ["p0001", "p0002", "claim1"]
    assert _by_key(chunks)["claim1"].text == "A widget 2008 the widget is round."


def test_첫_문단_번호는_점프_제한_안이어야_한다():
    chunks, _, check = _run(["2008 widgets in total.", "[0001] a.", "1. A widget."])
    assert _keys(chunks) == ["p0001", "claim1"]
    assert check["skipped_before_first"] == 1 and check["out_of_order"] == 0


def test_요약_제목_뒤_첫_줄이_빈_줄이어도_요약을_읽는다():
    lines = ["(57) ABSTRACT", "", "Made up abstract text.", "", "junk", "[0001] a.", "1. A widget."]
    chunks, warns, _ = _run(lines)
    assert _by_key(chunks)["abs"].text == "Made up abstract text."
    assert not any("요약 없음" in w for w in warns)


def test_요약이_비었거나_제목이_없으면_요약_없음_경고():
    _, warns, _ = _run(["(57) ABSTRACT", "(21) Appl. No.: 1", "[0001] a.", "1. A widget."])
    assert f"요약 없음: {DOC}" in warns
    _, warns, _ = _run(["[0001] a.", "1. A widget."])
    assert f"요약 없음: {DOC}" in warns


def test_청구항_앞부분_글자가_없으면_뒤_번호에서_시작하고_경고():
    lines = ["[0001] a.", "[0002] b.", "14. The widget of claim 13.", "15. The widget."]
    chunks, warns, _ = _run(lines)
    assert _keys(chunks) == ["p0001", "p0002", "claim14", "claim15"]
    assert _by_key(chunks)["p0002"].text == "b."
    assert f"청구항 1~13 글자층에 없음: {DOC}" in warns


def test_청구항_전부_취소는_청구항_없음과_경고():
    chunks, warns, _ = _run(["[0001] a.", "1.-20. (canceled)"])
    assert _keys(chunks) == ["p0001"]
    assert f"청구항 시작 못 찾음: {DOC}" in warns


def test_마지막_확정_번호_뒤에서_튄_번호는_세고_경고한다():
    nums = [f"[{n:04d}] p{n}." for n in [*range(1, 41), *range(100, 111)]]
    chunks, warns, check = _run([*nums, "What is claimed is:", "1. A widget."])
    assert check["last"] == 40 and check["after_last"] == 11
    assert f"문단 번호 끝 뒤 튐 무시: {DOC} 11개 (앞 문단 글자로 둠)" in warns
    assert "[0100] p100." in _by_key(chunks)["p0040"].text  # 글자는 앞 문단에 남는다


def test_두_줄로_꺾인_대문자_제목도_제목():
    lines = [
        "[0001] First part.",
        "DETAILED DESCRIPTION OF EXEMPLARY",
        "EMBODIMENTS",
        "[0002] Second.",
        "1. A widget.",
    ]
    c = _by_key(_run(lines)[0])
    assert c["p0001"].text == "First part."


def test_문단_번호가_없어도_청구항_머리_줄이_있으면_청구항을_만든다():
    lines = [
        "BACKGROUND",
        "Some text.",
        "What is claimed is:",
        "1. A widget.",
        "2. The widget of claim 1.",
    ]
    chunks, _, _ = _run(lines)
    assert _keys(chunks) == ["claim1", "claim2"]


def test_문단_번호가_0개면_후보는_표지_숫자로만_센다():
    # 확정 번호가 없으면 "끝 뒤 튐"은 없다 (같은 후보를 두 번 세지 않는다)
    chunks, warns, check = _run(["4321 widgets were sold", "What is claimed is:", "1. A widget."])
    assert _keys(chunks) == ["claim1"]
    assert check["skipped_before_first"] == 1
    assert check["after_last"] == 0
    assert not any("끝 뒤 튐" in w for w in warns)


def test_청구항_머리는_줄_전체가_머리일_때만():
    # 본문 줄 "We claim priority …" 는 머리가 아니라서 그 뒤의 문단 후보를 자르지 않는다
    lines = ["[0001] a.", "We claim priority to an earlier filing.", "[0002] b.", "1. A widget."]
    chunks, _, _ = _run(lines)
    assert _keys(chunks) == ["p0001", "p0002", "claim1"]
    assert _by_key(chunks)["p0001"].text == "a. We claim priority to an earlier filing."
    # 콜론 없이도, 앞뒤 공백이 있어도 머리
    chunks, _, _ = _run(["[0001] a.", "  We claim  ", "1. A widget."])
    assert _keys(chunks) == ["p0001", "claim1"]
