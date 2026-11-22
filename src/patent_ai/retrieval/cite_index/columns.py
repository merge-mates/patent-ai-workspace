"""두 단 PDF(미국 공보)를 단 순서대로 줄로 만든다.

pdfplumber의 extract_text()는 왼쪽·오른쪽 단의 줄을 섞어서 내놓는다. 그래서 단어 좌표를 받아
맨 위 머리줄 → 왼쪽 단 → 오른쪽 단 순서로 직접 줄을 만든다.
"""

from pathlib import Path
from statistics import median

import pdfplumber

from patent_ai.retrieval.cite_index.pages import PageText


def _rows(words: list[dict], line_tol: float) -> list[tuple[float, str]]:
    """단어를 위치 높이(top)가 비슷한 것끼리 한 줄로 묶는다. (줄 top, 글자) 목록."""
    rows: list[tuple[float, list[dict]]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        # 줄의 첫 단어 top과 line_tol 이내면 같은 줄
        if rows and w["top"] - rows[-1][0] <= line_tol:
            rows[-1][1].append(w)
        else:
            rows.append((w["top"], [w]))
    return [
        (top, " ".join(x["text"] for x in sorted(ws, key=lambda x: x["x0"]))) for top, ws in rows
    ]


def _column(words: list[dict], line_tol: float, gap_factor: float) -> list[str]:
    rows = _rows(words, line_tol)
    gaps = [b[0] - a[0] for a, b in zip(rows, rows[1:], strict=False)]
    typical = median(gaps) if gaps else 0.0
    out: list[str] = []
    for i, (top, text) in enumerate(rows):
        # 줄 간격이 보통의 gap_factor배보다 크면 빈 줄 (그림 글자·문단 사이 등)
        if i > 0 and typical > 0 and top - rows[i - 1][0] > gap_factor * typical:
            out.append("")
        out.append(text)
    return out


def column_lines(
    words: list[dict], width: float, line_tol: float = 3.0, gap_factor: float = 2.0
) -> list[str]:
    """쪽의 단어(extract_words 결과)를 줄 목록으로. 머리줄 + 왼쪽 단 + [""] + 오른쪽 단.

    빈 문자열 ""은 단 경계 또는 큰 세로 간격 표시다.
    """
    if not words:
        return []
    min_top = min(w["top"] for w in words)
    header = [w for w in words if w["top"] - min_top <= line_tol]  # 맨 위 전체 폭 줄
    body = [w for w in words if w["top"] - min_top > line_tol]
    left = [w for w in body if (w["x0"] + w["x1"]) / 2 < width / 2]
    right = [w for w in body if (w["x0"] + w["x1"]) / 2 >= width / 2]

    lines = [" ".join(w["text"] for w in sorted(header, key=lambda w: w["x0"]))]
    lines += _column(left, line_tol, gap_factor)
    if left and right:
        lines.append("")  # 단 경계
    lines += _column(right, line_tol, gap_factor)
    return lines


class PdfplumberColumnExtractor:
    """두 단 PDF용 구현. 글자가 없는 쪽은 빈 lines로 남긴다."""

    def __init__(self, line_tol: float = 3.0, gap_factor: float = 2.0):
        # 설정 파일 us_columns 값이 들어온다
        self.line_tol, self.gap_factor = line_tol, gap_factor

    def extract(self, pdf_path: Path) -> list[PageText]:
        path = Path(pdf_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        pages: list[PageText] = []
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages, 1):
                words = page.extract_words()
                pages.append(
                    PageText(
                        page=i,
                        lines=column_lines(
                            words, float(page.width), self.line_tol, self.gap_factor
                        ),
                    )
                )
        return pages
