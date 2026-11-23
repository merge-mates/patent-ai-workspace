"""두 단 PDF(미국 공보)를 단 순서대로 줄로 만든다.

pdfplumber의 extract_text()는 왼쪽·오른쪽 단의 줄을 섞어서 내놓는다. 그래서 단어 좌표를 받아
맨 위 머리줄 → 왼쪽 단 → 오른쪽 단 순서로 직접 줄을 만든다.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from statistics import median

import pdfplumber
import yaml

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


# --- 미국 등록공보: 여백 줄 번호(5, 10, ..., 65)로 줄을 센다 ---
_DEFAULT_CONFIG = Path(__file__).resolve().parents[4] / "config" / "cite_search.yaml"
_GUTTER_NUM = re.compile(r"^\d{1,2}$")
_COLUMN_NUM = re.compile(r"\d{1,3}")
_SHEET = re.compile(r"Sheet\s*\d+\s*of\s*\d+", re.IGNORECASE)


def is_drawing_sheet(header: str) -> bool:
    """머리줄에 "Sheet N of M"이 있으면 도면 쪽."""
    return bool(_SHEET.search(header))


@dataclass(frozen=True)
class GrantedConfig:
    """설정 파일 us_granted 칸. 기본값은 설정 파일과 같다."""

    min_points: int = 3  # 줄 맞춤에 쓸 여백 숫자 최소 개수
    x_tol: float = 8.0  # 여백 숫자가 여백 x에서 벗어나도 되는 폭 (pt)
    residual_limit: float = 1.0  # 맞춤선에서 이만큼(줄) 넘게 벗어난 숫자는 버린다
    gutter_x_min: float = 0.4  # 여백 숫자가 있을 수 있는 x 범위 (쪽 너비 비율)
    gutter_x_max: float = 0.6
    lines_per_chunk: int = 15  # 조각 하나가 담는 줄 번호 폭

    @classmethod
    def from_dict(cls, cfg: dict) -> GrantedConfig:
        lo, hi = cfg.get("gutter_x_range", (cls.gutter_x_min, cls.gutter_x_max))
        return cls(
            min_points=int(cfg.get("min_points", cls.min_points)),
            x_tol=float(cfg.get("x_tol", cls.x_tol)),
            residual_limit=float(cfg.get("residual_limit", cls.residual_limit)),
            gutter_x_min=float(lo),
            gutter_x_max=float(hi),
            lines_per_chunk=int(cfg.get("lines_per_chunk", cls.lines_per_chunk)),
        )


def load_granted_config(path: Path = _DEFAULT_CONFIG) -> GrantedConfig:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")).get("us_granted") or {}
    return GrantedConfig.from_dict(cfg)


@dataclass
class ColumnLayout:
    """줄을 센 본문 쪽 하나."""

    printed: tuple[int | None, int | None]  # 쪽 위에 인쇄된 (왼쪽, 오른쪽) 칼럼 번호
    left: list[tuple[int, str]]  # (줄 번호, 글자)
    right: list[tuple[int, str]]
    max_residual: float  # 맞춤선과 여백 숫자의 최대 차이 (줄)
    fit: tuple[float, float, float] = (0.0, 0.0, 0.0)  # (a, b, 여백 x): 뒤쪽이 다시 쓴다
    reused: bool = False  # 여백 숫자가 모자라 앞 쪽 맞춤을 다시 쓴 쪽


@dataclass
class GrantedPage:
    page: int
    lines: list[str]  # column_lines 결과 (요약 찾기·쪽 조각 대체용)
    columns: ColumnLayout | None  # 줄을 못 센 쪽(표지·도면)은 None


def _fit(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    """(top, 줄 번호) 점들의 최소제곱 직선 줄 = a*top + b."""
    n = len(points)
    mx = sum(t for t, _ in points) / n
    my = sum(v for _, v in points) / n
    sxx = sum((t - mx) ** 2 for t, _ in points)
    if sxx == 0:
        return None
    a = sum((t - mx) * (v - my) for t, v in points) / sxx
    return a, my - a * mx


def _robust_fit(
    points: list[tuple[float, float]], limit: float, min_points: int
) -> tuple[float, float, float] | None:
    """가장 어긋난 점부터 하나씩 버리며 다시 맞춘다. (a, b, 최대 차이) 또는 None."""
    pts = list(points)
    while len(pts) >= min_points and len({v for _, v in pts}) >= min_points:
        fit = _fit(pts)
        if fit is None or fit[0] <= 0:
            return None
        a, b = fit
        res = [abs(a * t + b - v) for t, v in pts]
        worst = max(range(len(pts)), key=res.__getitem__)
        if res[worst] <= limit:
            return a, b, res[worst]
        del pts[worst]
    return None


def column_line_page(
    words: list[dict],
    width: float,
    config: GrantedConfig | None = None,
    line_tol: float = 3.0,
    prior: tuple[float, float, float] | None = None,
) -> ColumnLayout | None:
    """등록공보 본문 쪽의 단어에서 칼럼 번호·줄 번호가 붙은 글자를 만든다. 줄을 못 세면 None.

    prior = 앞 본문 쪽의 맞춤 (a, b, 여백 x). 이 쪽 혼자 못 맞추면(끝 쪽처럼 줄이 적은 쪽)
    같은 문헌은 줄 위치가 같으니 그것을 다시 쓴다. 도면 쪽(Sheet N of M)은 다시 쓰지 않는다.
    """
    cfg = config or GrantedConfig()
    if not words:
        return None
    own = _own_fit(words, width, cfg)
    if own is not None:
        (a, b, gx), max_res, reused = own[0], own[1], False
    elif prior is not None:
        top = min(w["top"] for w in words)
        header = " ".join(
            w["text"] for w in sorted(words, key=lambda w: w["x0"]) if w["top"] - top <= line_tol
        )
        if is_drawing_sheet(header):
            return None
        (a, b, gx), max_res, reused = prior, 0.0, True
    else:
        return None
    layout = _layout(words, cfg, a, b, gx, max_res, line_tol)
    if reused:
        # 다시 쓴 맞춤으로 본문 줄이 하나도 안 나오면 본문 쪽이 아니다
        if not (layout.left or layout.right):
            return None
        layout.reused = True
    return layout


def _own_fit(words: list[dict], width: float, cfg: GrantedConfig):
    """이 쪽 여백 숫자만으로 맞춘 ((a, b, 여백 x), 최대 차이) 또는 None."""
    # 1) 여백 숫자 후보: 1~2자리 숫자 중 5의 배수, 쪽 가운데 띠 안
    cand = [
        w
        for w in words
        if _GUTTER_NUM.match(w["text"])
        and int(w["text"]) % 5 == 0
        and int(w["text"]) > 0
        and cfg.gutter_x_min * width <= (w["x0"] + w["x1"]) / 2 <= cfg.gutter_x_max * width
    ]
    if len(cand) < cfg.min_points:
        return None
    # 여백은 쪽마다 x가 하나라, 중앙값에서 먼 숫자는 본문 속 숫자로 보고 뺀다
    gx = median((w["x0"] + w["x1"]) / 2 for w in cand)
    cand = [w for w in cand if abs((w["x0"] + w["x1"]) / 2 - gx) <= cfg.x_tol]
    fit = _robust_fit(
        [(w["top"], float(w["text"])) for w in cand], cfg.residual_limit, cfg.min_points
    )
    if fit is None:
        return None
    a, b, max_res = fit
    return (a, b, gx), max_res


def _layout(
    words: list[dict],
    cfg: GrantedConfig,
    a: float,
    b: float,
    gx: float,
    max_res: float,
    line_tol: float,
) -> ColumnLayout:
    # 2) 여백 숫자(맞춤에서 버린 것 포함)는 글자에서 뺀다
    gutter_ids = {
        id(w)
        for w in words
        if _GUTTER_NUM.match(w["text"]) and abs((w["x0"] + w["x1"]) / 2 - gx) <= cfg.x_tol
    }
    min_top = min(w["top"] for w in words)
    printed: list[int | None] = [None, None]
    rows: tuple[dict[int, list[dict]], dict[int, list[dict]]] = ({}, {})
    for w in words:
        if id(w) in gutter_ids:
            continue
        side = 0 if (w["x0"] + w["x1"]) / 2 < gx else 1
        line = round(a * w["top"] + b)
        if line >= 1:
            rows[side].setdefault(line, []).append(w)
        elif w["top"] - min_top > line_tol and printed[side] is None:
            # 머리줄 아래 첫 줄 앞의 숫자 = 인쇄된 칼럼 번호 (OCR이 못 읽으면 None)
            m = _COLUMN_NUM.search(w["text"])
            if m:
                printed[side] = int(m.group())
        # 머리줄과 칼럼 번호줄의 나머지 글자는 버린다

    def join(side_rows: dict[int, list[dict]]) -> list[tuple[int, str]]:
        return [
            (n, " ".join(x["text"] for x in sorted(ws, key=lambda x: x["x0"])))
            for n, ws in sorted(side_rows.items())
        ]

    return ColumnLayout(
        (printed[0], printed[1]),
        join(rows[0]),
        join(rows[1]),
        round(max_res, 3),
        fit=(a, b, gx),
    )


class PdfplumberGrantedExtractor:
    """등록공보용: 쪽마다 줄 목록(요약용)과 칼럼·줄 배치(본문 쪽만)를 돌려준다."""

    def __init__(
        self, config: GrantedConfig | None = None, line_tol: float = 3.0, gap_factor: float = 2.0
    ):
        self.config, self.line_tol, self.gap_factor = (
            config or GrantedConfig(),
            line_tol,
            gap_factor,
        )

    def extract(self, pdf_path: Path) -> list[GrantedPage]:
        path = Path(pdf_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        pages: list[GrantedPage] = []
        prior = None  # 앞 본문 쪽의 맞춤
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages, 1):
                words = page.extract_words()
                width = float(page.width)
                lay = column_line_page(words, width, self.config, self.line_tol, prior)
                if lay is not None and not lay.reused:
                    prior = lay.fit  # 스스로 맞춘 쪽의 맞춤만 이어 쓴다
                pages.append(
                    GrantedPage(
                        page=i,
                        lines=column_lines(words, width, self.line_tol, self.gap_factor),
                        columns=lay,
                    )
                )
        return pages
