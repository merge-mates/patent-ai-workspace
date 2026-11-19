"""머리말·꼬리말·쪽 번호 빼기 (요구 3). 줄 목록만 쓰고 PDF는 안 읽는다."""

from pathlib import Path

from patent_ai.retrieval.cite_index import (
    PageText,
    load_header_footer_config,
    strip_repeated,
)

KEEP = [r"^[【\[]\d{4}[】\]]", r"^청구항\s*\d+"]


def _공보(tops=None):
    # 지어낸 3쪽: 쪽마다 머리말(번호 같음)·꼬리말(`- n -`)·본문 두 줄
    pages = []
    for i in (1, 2, 3):
        body = [f"본문 {i}쪽 첫째 줄", f"본문 {i}쪽 둘째 줄"]
        if tops:
            body[0] = tops[i - 1]
        pages.append(PageText(page=i, lines=["공개특허 10-2099-0000001", *body, f"- {i} -"]))
    return pages


def test_머리말_꼬리말_빠지고_본문_남음():
    out, removed = strip_repeated(_공보(), 3, 0.5, KEEP)
    assert removed == 6
    assert out[0].lines == ["본문 1쪽 첫째 줄", "본문 1쪽 둘째 줄"]
    assert [p.page for p in out] == [1, 2, 3]


def test_식별번호_줄은_맨_위여도_남음():
    # 숫자를 #로 바꾸면 세 쪽 모두 `【####】`라 되풀이로 보이지만 keep_patterns라 남는다
    out, removed = strip_repeated(_공보(["【0012】", "[0019]", "【0025】"]), 3, 0.5, KEEP)
    assert removed == 6
    assert [p.lines[0] for p in out] == ["【0012】", "[0019]", "【0025】"]


def test_청구항_머리는_남음():
    pages = [
        PageText(page=i, lines=[f"청구항 {i}.", "본문", "공보 번호", f"- {i} -"]) for i in (1, 2, 3)
    ]
    out, _ = strip_repeated(pages, 4, 0.5, KEEP)
    assert all(p.lines[0] == f"청구항 {i}." for i, p in enumerate(out, 1))


def test_한쪽_문헌은_아무것도_안_뺌():
    pages = [PageText(page=1, lines=["공개특허 10-1", "본문", "- 1 -"])]
    out, removed = strip_repeated(pages, 3, 0.5, KEEP)
    assert removed == 0
    assert out == pages


def test_글자_없는_쪽은_빈_lines():
    pages = _공보()
    pages[1] = PageText(page=2, lines=[])
    out, _ = strip_repeated(pages, 3, 0.5, KEEP)
    assert out[1].lines == []
    assert out[1].page == 2


def test_도면쪽도_머리말_꼬리말만_빠짐():
    pages = _공보()
    pages[2] = PageText(page=3, lines=["공개특허 10-2099-0000001", "도면8", "- 3 -"])
    out, removed = strip_repeated(pages, 3, 0.5, KEEP)
    assert out[2].lines == ["도면8"]
    assert removed == 6


def test_입력_안_바뀜():
    pages = _공보()
    before = [list(p.lines) for p in pages]
    strip_repeated(pages, 3, 0.5, KEEP)
    assert [p.lines for p in pages] == before


def test_비율_미달이면_안_뺌():
    # 4쪽 중 1쪽에만 나오는 줄은 min_page_ratio 0.5 미달
    pages = [PageText(page=i, lines=[f"고유 {i}", "본문"]) for i in (1, 2, 3, 4)]
    pages[0].lines.insert(0, "한 번만")
    out, removed = strip_repeated(pages, 3, 0.5, KEEP)
    assert removed == 0


def test_설정_파일_값():
    cfg = load_header_footer_config(
        Path(__file__).parent.parent.parent / "config" / "cite_search.yaml"
    )
    assert cfg.scan_lines >= 1
    assert 0 < cfg.min_page_ratio <= 1
    out, removed = strip_repeated(_공보(), cfg.scan_lines, cfg.min_page_ratio, cfg.keep_patterns)
    assert removed == 6
