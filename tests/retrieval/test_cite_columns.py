"""두 단 PDF 줄 만들기. 단어 좌표는 모두 지어낸 것 (pdfplumber extract_words 꼴)."""

from pathlib import Path

import pytest

from patent_ai.retrieval.cite_index.columns import PdfplumberColumnExtractor, column_lines


def _w(text, x0, top, w=20.0):
    return {"text": text, "x0": x0, "x1": x0 + w, "top": top}


WIDTH = 600.0


def test_빈_단어_목록은_빈_줄():
    assert column_lines([], WIDTH) == []


def test_왼쪽_단을_다_읽고_오른쪽_단을_읽는다_맨_위_머리줄이_먼저():
    words = [
        # 맨 위 전체 폭 머리줄 (왼쪽·오른쪽에 걸침)
        _w("HEAD", 50, 10),
        _w("RIGHT", 400, 10),
        # 왼쪽 단과 오른쪽 단 줄이 섞여 들어옴
        _w("l1b", 90, 50),
        _w("r1", 350, 50),
        _w("l1a", 50, 50),
        _w("l2", 50, 60),
        _w("r2", 350, 60),
    ]
    assert column_lines(words, WIDTH) == ["HEAD RIGHT", "l1a l1b", "l2", "", "r1", "r2"]


def test_줄_높이가_조금_달라도_한_줄로_묶는다():
    words = [_w("h", 50, 5), _w("a", 50, 50.0), _w("b", 80, 52.5), _w("c", 50, 60.0)]
    assert column_lines(words, WIDTH) == ["h", "a b", "c"]
    # 허용 오차를 줄이면 a와 b가 다른 줄이 된다
    assert column_lines(words, WIDTH, line_tol=1.0) == ["h", "a", "b", "c"]


def test_추출기는_설정값을_받는다():
    ex = PdfplumberColumnExtractor(line_tol=1.5, gap_factor=3.0)
    assert (ex.line_tol, ex.gap_factor) == (1.5, 3.0)


def test_설정_파일에_두_단_값이_있다():
    import yaml

    cfg = yaml.safe_load((Path(__file__).parents[2] / "config" / "cite_search.yaml").read_text())
    assert cfg["us_columns"] == {"line_tol": 3.0, "gap_factor": 2.0}
    assert cfg["us_chunking"]["max_number_jump"] == 50


def test_세로로_크게_벌어지면_빈_줄을_끼운다():
    words = [_w("h", 50, 5)]
    # 왼쪽 단: 간격 10 10 10 그리고 40 (중앙값 10의 2배 초과)
    for i, top in enumerate([20, 30, 40, 50, 90]):
        words.append(_w(f"l{i}", 50, top))
    assert column_lines(words, WIDTH) == ["h", "l0", "l1", "l2", "l3", "", "l4"]


def test_한쪽_단만_있으면_단_경계_빈_줄을_넣지_않는다():
    words = [_w("h", 50, 5), _w("a", 50, 20), _w("b", 50, 30)]
    assert column_lines(words, WIDTH) == ["h", "a", "b"]


def test_파일이_없으면_FileNotFoundError(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        PdfplumberColumnExtractor().extract(tmp_path / "nope.pdf")
