"""미국 등록공보 칼럼·줄 조각. 단어 좌표와 글자는 모두 지어낸 것 (pdfplumber extract_words 꼴).

가짜 쪽: 너비 600, 줄 L의 top = 10*L + 75 (줄 = 0.1*top - 7.5), 가운데 여백 x 300.
"""

import yaml

from patent_ai.retrieval.cite_index.__main__ import build_index
from patent_ai.retrieval.cite_index.chunker import (
    chunk_document_checked,
    is_granted_doc,
    load_us_chunking_config,
)
from patent_ai.retrieval.cite_index.columns import (
    GrantedConfig,
    GrantedPage,
    column_line_page,
    load_granted_config,
)
from patent_ai.retrieval.cite_index.pages import PageText
from tests.retrieval.test_cite_index import CONFIG, FakeExtractor

WIDTH = 600.0


def _w(text, x0, top, w=10.0):
    return {"text": text, "x0": x0, "x1": x0 + w, "top": top}


def _top(line):
    return 10.0 * line + 75.0


def text_page(left_no="1", right_no="2", n_lines=75, outlier=False, mark="", gutter=None):
    """본문 쪽: 머리줄, 칼럼 번호줄, 여백 줄 번호 5..65, 줄마다 왼쪽·오른쪽 글자 하나."""
    words = [_w("US", 200, 54), _w("0,000,000", 240, 54)]
    if left_no is not None:
        words.append(_w(left_no, 150, 68))
    if right_no is not None:
        words.append(_w(right_no, 450, 68))
    for n in range(5, 66, 5) if gutter is None else gutter:
        words.append(_w(str(n), 295, _top(n)))
    if outlier:
        words.append(_w("10", 297, _top(18.4)))  # 엉뚱한 높이의 숫자 하나
    for line in range(1, n_lines + 1):
        words.append(_w(f"L{mark}{line}", 50, _top(line)))
        words.append(_w(f"R{mark}{line}", 350, _top(line)))
    return words


def test_여백_줄_번호로_줄을_맞추고_좌우로_나눈다():
    p = column_line_page(text_page(n_lines=3), WIDTH)
    assert p is not None
    assert p.printed == (1, 2)
    assert p.left == [(1, "L1"), (2, "L2"), (3, "L3")]
    assert p.right == [(1, "R1"), (2, "R2"), (3, "R3")]
    assert p.max_residual < 0.1


def test_여백_숫자와_칼럼_번호와_머리줄은_글자에_안_들어간다():
    p = column_line_page(text_page(n_lines=10), WIDTH)
    joined = " ".join(t for _, t in p.left + p.right)
    for banned in ("US", "0,000,000", "5", "10"):
        assert banned not in joined.split()
    assert all(n >= 1 for n, _ in p.left + p.right)


def test_같은_줄의_단어는_x_순서로_공백으로_잇는다():
    words = text_page(n_lines=2) + [_w("second", 120, _top(1))]
    p = column_line_page(words, WIDTH)
    assert p.left[0] == (1, "L1 second")


def test_엉뚱한_높이의_숫자_하나는_버리고_다시_맞춘다():
    p = column_line_page(text_page(n_lines=3, outlier=True), WIDTH)
    assert p is not None
    assert p.left[0][0] == 1 and p.max_residual < 0.1


def test_여백_숫자가_3개_미만이면_본문_쪽이_아니다():
    two = [
        w
        for w in text_page()
        if not (w["text"].isdigit() and w["x0"] == 295 and int(w["text"]) > 10)
    ]
    assert column_line_page(two, WIDTH) is None
    assert column_line_page([], WIDTH) is None
    # 여백 밖에 있는 숫자는 세지 않는다
    far = [_w(str(n), 100, _top(n)) for n in range(5, 66, 5)]
    assert column_line_page(far, WIDTH) is None


def test_칼럼_번호가_없거나_못_읽으면_None():
    p = column_line_page(text_page(left_no="[]", right_no=None, n_lines=2), WIDTH)
    assert p.printed == (None, None)
    p = column_line_page(text_page(left_no="7.", right_no="8", n_lines=2), WIDTH)
    assert p.printed == (7, 8)


def test_설정_파일에_등록공보_값이_있고_함수_기본값과_같다():
    cfg = load_granted_config()
    assert cfg == GrantedConfig()
    assert cfg.lines_per_chunk == 15 and cfg.min_points == 3


def gp(page, words=None, lines=None):
    """GrantedPage: 단어에서 칼럼 배치를 읽고, 줄은 따로 준다."""
    layout = column_line_page(words, WIDTH) if words else None
    return GrantedPage(page=page, lines=lines or [], columns=layout)


def doc_pages():
    front = gp(1, None, ["57 ABSTRACT", "Made up abstract of FIG. 2 here.", "(21) Appl. No."])
    drawing = gp(2, None, ["US 0,000,000 B2 Sheet 1 of 1", "FIG. 1"])
    t1 = gp(3, text_page("1", "2", mark="a"), ["x"])
    t2 = gp(4, text_page("3", "4", mark="b"), ["x"])
    return [front, drawing, t1, t2]


def chunk(doc_id, pages):
    return chunk_document_checked(doc_id, pages, "cite-idx-v1", us_config=load_us_chunking_config())


def test_칼럼과_줄_창으로_조각을_만든다_아이디_위치_라벨():
    chunks, warns, check = chunk("US0000001B2", doc_pages())
    by_id = {c.chunk_id: c for c in chunks}
    c = by_id["cite-idx-v1:US0000001B2:3:1-15"]
    assert c.chunk_kind == "body"
    loc = c.location
    assert (loc.kind, loc.start, loc.end, loc.label) == ("column_line", 30001, 30015, "3:1-15")
    assert c.text.startswith("Lb1 Lb2") and "Lb15" in c.text and "Lb16" not in c.text
    # 쪽 둘 x 칼럼 둘 x 창 다섯
    assert sum(1 for x in chunks if x.chunk_kind == "body") == 20
    assert "cite-idx-v1:US0000001B2:4:61-75" in by_id
    assert "cite-idx-v1:US0000001B2:1:1-15" in by_id
    assert by_id["cite-idx-v1:US0000001B2:2:16-30"].location.start == 20016


def test_창의_처음과_끝은_실제_줄_번호():
    page = text_page("1", "2", n_lines=75)
    # 20~22줄 글자를 지워 둔다
    page = [w for w in page if not (w["text"][0] in "LR" and w["text"][1:] in {"20", "21", "22"})]
    chunks, _, _ = chunk("US0000001B2", [gp(1, page, ["x"])])
    ids = {c.chunk_id.split(":", 2)[2] for c in chunks}
    assert "1:16-30" in ids  # 16~30 창은 그대로
    page2 = [w for w in text_page() if not (w["text"][0] in "LR" and int(w["text"][1:]) > 40)]
    chunks, _, _ = chunk("US0000001B2", [gp(1, page2, ["x"])])
    assert "1:31-40" in {c.chunk_id.split(":", 2)[2] for c in chunks}


def test_요약은_1쪽_줄에서_만든다():
    chunks, _, _ = chunk("US0000001B2", doc_pages())
    a = [c for c in chunks if c.chunk_kind == "abstract"]
    assert len(a) == 1 and a[0].chunk_id.endswith(":abs")
    assert a[0].text == "Made up abstract of FIG. 2 here." and a[0].location.figures == [2]


def test_본문_쪽이_아닌_쪽은_건너뛰고_세어_보고한다():
    _, warns, check = chunk("US0000001B2", doc_pages())
    assert check["text_pages"] == 2 and check["skipped_pages"] == 2
    assert check["column_number_mismatch"] == 0
    assert check["max_residual"] < 0.1
    assert not any("불일치" in w for w in warns)


def test_인쇄_번호를_쓰고_못_읽으면_앞_쪽에_2를_더한다_다르면_경고로_센다():
    pages = [
        gp(1, text_page("1", "2", n_lines=2, mark="a")),
        gp(2, text_page("4", None, n_lines=2, mark="b")),  # 3,4 이어야 하는데 왼쪽 4
        gp(3, text_page(None, None, n_lines=2, mark="c")),  # 못 읽음: 앞 왼쪽 4 + 2
        gp(4, text_page(None, "9", n_lines=2, mark="d")),  # 오른쪽 9 -> 왼쪽 8 (맞음)
    ]
    chunks, warns, check = chunk("US0000001B2", pages)
    labels = {c.location.label for c in chunks}
    assert labels == {f"{c}:1-2" for c in (1, 2, 4, 5, 6, 7, 8, 9)}
    assert check["column_number_mismatch"] == 1  # 2쪽 왼쪽 4 (기대 3)만. 오른쪽은 못 읽음
    assert any("불일치" in w and "1개" in w for w in warns)


def short_words(n_lines, left_no, right_no, gutter):
    return text_page(left_no, right_no, n_lines=n_lines, mark="s", gutter=gutter)


def test_여백_숫자가_모자란_뒤쪽_본문_쪽은_앞_쪽_맞춤을_다시_쓴다():
    first = column_line_page(text_page(), WIDTH)
    for gutter in ([5], []):  # 마지막 쪽: 여백 숫자 1개, 0개
        words = short_words(8, "17", "18", gutter)
        assert column_line_page(words, WIDTH) is None  # 혼자서는 못 맞춘다
        p = column_line_page(words, WIDTH, prior=first.fit)
        assert p is not None and p.reused and p.printed == (17, 18)
        assert [n for n, _ in p.left] == list(range(1, 9))
        assert "5" not in " ".join(t for _, t in p.left + p.right).split()


def test_도면_쪽과_앞_쪽_없는_쪽은_맞춤을_다시_쓰지_않는다():
    first = column_line_page(text_page(), WIDTH)
    sheet = [_w("US", 200, 54), _w("Sheet", 300, 54), _w("1", 340, 54), _w("of", 360, 54)]
    sheet += [_w("2", 380, 54), _w("FIG", 100, 200), _w("a", 200, 300)]
    assert column_line_page(sheet, WIDTH, prior=first.fit) is None
    assert column_line_page(short_words(8, "1", "2", []), WIDTH) is None  # prior 없음


def test_중간_쪽이_여백_숫자_1개여도_뒤_쪽_칼럼_번호가_밀리지_않는다():
    l1 = column_line_page(text_page("1", "2", n_lines=8, mark="a"), WIDTH)
    l2 = column_line_page(short_words(8, "3", "4", [5]), WIDTH, prior=l1.fit)
    l3 = column_line_page(text_page("5", "6", n_lines=8, mark="c"), WIDTH)
    pages = [GrantedPage(i, ["x"], lay) for i, lay in enumerate((l1, l2, l3), 1)]
    chunks, warns, check = chunk("US0000001B2", pages)
    assert {c.location.label for c in chunks} == {f"{c}:1-8" for c in range(1, 7)}
    assert any(c.text.startswith("Ls1") for c in chunks)  # 2쪽 글자가 살아 있다
    assert check["text_pages"] == 3 and check["reused_fit_pages"] == 1
    assert check["uncounted_text_pages"] == 0 and check["column_number_mismatch"] == 0


def test_끝내_못_세는_중간_본문_쪽은_쪽_조각과_경고_번호는_인쇄값으로_이어간다():
    l1 = column_line_page(text_page("1", "2", n_lines=3, mark="a"), WIDTH)
    l3 = column_line_page(text_page("5", "6", n_lines=3, mark="c"), WIDTH)
    pages = [
        GrantedPage(1, ["x"], l1),
        GrantedPage(2, ["US 0 B2", "Made up leftover text"], None),
        GrantedPage(3, ["x"], l3),
        # 뒤따르는 도면 쪽은 본문 쪽으로 세지 않는다
        GrantedPage(4, ["US 0 B2 Sheet 1 of 1", "FIG. 1"], None),
    ]
    chunks, warns, check = chunk("US0000001B2", pages)
    ids = {c.chunk_id.split(":", 2)[2] for c in chunks}
    assert {"1:1-3", "2:1-3", "5:1-3", "6:1-3", "pg2"} <= ids and "pg4" not in ids
    pg = next(c for c in chunks if c.chunk_id.endswith(":pg2"))
    assert pg.location.kind == "page" and "leftover" in pg.text
    assert "본문 쪽 줄 못 셈: US0000001B2 2쪽 page 조각으로" in warns
    assert check["uncounted_text_pages"] == 1 and check["skipped_pages"] == 1
    assert check["column_number_mismatch"] == 0  # 못 센 쪽 몫(+2)을 기대에 넣는다


def test_첫_본문_쪽의_인쇄_번호에서_시작하고_없으면_1():
    chunks, _, _ = chunk("US0000001B2", [gp(1, text_page("5", "6", n_lines=2))])
    assert {c.location.label for c in chunks} == {"5:1-2", "6:1-2"}
    chunks, _, _ = chunk("US0000001B2", [gp(1, text_page(None, None, n_lines=2))])
    assert {c.location.label for c in chunks} == {"1:1-2", "2:1-2"}


def test_줄을_못_세는_문헌은_쪽_조각과_경고():
    pages = [
        GrantedPage(page=1, lines=["Made up front."], columns=None),
        GrantedPage(page=2, lines=[], columns=None),
        GrantedPage(page=3, lines=["Made up page three."], columns=None),
    ]
    chunks, warns, _ = chunk("US0000001B2", pages)
    assert [c.chunk_id for c in chunks] == [
        "cite-idx-v1:US0000001B2:pg1",
        "cite-idx-v1:US0000001B2:pg3",
    ]
    assert chunks[1].location.kind == "page" and chunks[1].location.label == "3쪽"
    assert "칼럼·줄 못 셈: US0000001B2 page 조각으로" in warns


def test_등록공보_번호만_새_경로로_간다():
    for d in ("US0000002A", "US7176960B1", "US0000003B1", "US0000001B2"):
        assert is_granted_doc(d)
    for d in ("US20200001234A1", "US20200001234A9", "KR100A", "NPL-x", "US123456789A"):
        assert not is_granted_doc(d)


def test_공개공보와_한국은_그대로():
    us = load_us_chunking_config()
    for head in ("(57) ABSTRACT", "57 ABSTRACT"):  # 괄호가 OCR에서 빠진 꼴도
        pages = [PageText(page=1, lines=[head, "Made up."])]
        chunks, _, check = chunk_document_checked(
            "US20200001234A1", pages, "cite-idx-v1", us_config=us
        )
        assert chunks[0].location.kind == "abstract" and "accepted" in check
        assert "text_pages" not in check
    kr = [PageText(page=1, lines=["[0001] 지어낸 첫 문단", "[0002] 지어낸 둘째 문단"])]
    chunks, _, check = chunk_document_checked("KR100A", kr, "cite-idx-v1")
    assert [c.location.kind for c in chunks] == ["paragraph", "paragraph"] and check is None


def test_등록공보_쪽_조각은_되풀이_머리줄을_뺀다(tmp_path):
    raw = tmp_path / "raw" / "c1"
    raw.mkdir(parents=True)
    (raw / "US0000001B2.pdf").write_bytes(b"%PDF fake")
    table = tmp_path / "ids.yaml"
    table.write_text(yaml.safe_dump({"doc_ids": {}, "skip": []}), encoding="utf-8")
    cfg = dict(CONFIG)
    cfg.update(
        raw_root=str(tmp_path / "raw"), doc_id_table=str(table), report_dir=str(tmp_path / "w")
    )
    pages = [
        GrantedPage(i, [f"US 0,000,00{i} B2", f"Made up body {'abcd'[i - 1]}"], None)
        for i in range(1, 5)
    ]
    chunks, _ = build_index(cfg, FakeExtractor({}), granted_extractor=_Granted(pages))
    assert len(chunks) == 4 and all("B2" not in c.text for c in chunks)
    assert all(c.text.startswith("Made up body") for c in chunks)


class _Granted:
    def __init__(self, pages):
        self.pages, self.calls = pages, 0

    def extract(self, pdf_path):
        self.calls += 1
        return self.pages


def test_build_index는_등록공보_파일을_등록공보_추출기로_보낸다(tmp_path):
    raw = tmp_path / "raw" / "c1"
    raw.mkdir(parents=True)
    (raw / "US0000001B2.pdf").write_bytes(b"%PDF fake")
    (raw / "KR100A.pdf").write_bytes(b"%PDF fake2")
    table = tmp_path / "ids.yaml"
    table.write_text(yaml.safe_dump({"doc_ids": {}, "skip": []}), encoding="utf-8")
    cfg = dict(CONFIG)
    cfg.update(
        raw_root=str(tmp_path / "raw"), doc_id_table=str(table), report_dir=str(tmp_path / "w")
    )
    kr = [PageText(page=1, lines=["청구범위", "청구항 1", "지어낸 장치."])]
    other = FakeExtractor({"KR100A.pdf": kr})
    granted = _Granted(doc_pages())
    chunks, report = build_index(cfg, other, granted_extractor=granted)
    assert granted.calls == 1 and other.calls == 1
    d = report.to_dict()["docs"]["US0000001B2"]
    assert d["column_check"]["text_pages"] == 2 and "paragraph_check" not in d
    assert {c.doc_id for c in chunks} == {"US0000001B2", "KR100A"}
