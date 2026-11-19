"""쪽마다 되풀이되는 머리말·꼬리말·쪽 번호 줄 빼기 (design 2절 2단계)."""

import math
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from patent_ai.retrieval.cite_index.pages import PageText


@dataclass
class HeaderFooterConfig:
    scan_lines: int
    min_page_ratio: float
    keep_patterns: list[str]


def load_header_footer_config(path: Path) -> HeaderFooterConfig:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["header_footer"]
    return HeaderFooterConfig(
        scan_lines=int(cfg["scan_lines"]),
        min_page_ratio=float(cfg["min_page_ratio"]),
        keep_patterns=list(cfg.get("keep_patterns", [])),
    )


def _normalize(line: str) -> str:
    # 쪽마다 달라지는 숫자(쪽 번호 등)를 #로 바꿔 같은 줄로 센다
    return re.sub(r"\d+", "#", line.strip())


def _scan_indexes(n_lines: int, scan_lines: int) -> set[int]:
    # 위 scan_lines줄과 아래 scan_lines줄의 위치 (짧은 쪽은 겹쳐도 한 번만)
    top = range(min(scan_lines, n_lines))
    bottom = range(max(n_lines - scan_lines, 0), n_lines)
    return set(top) | set(bottom)


def strip_repeated(
    pages: list[PageText],
    scan_lines: int,
    min_page_ratio: float,
    keep_patterns: list[str],
) -> tuple[list[PageText], int]:
    """되풀이되는 위·아래 줄을 뺀 새 쪽 목록과 뺀 줄 수를 돌려준다. 입력은 안 바꾼다."""
    keeps = [re.compile(p) for p in keep_patterns]

    def is_kept(line: str) -> bool:
        return any(k.search(line.strip()) for k in keeps)

    def candidates(page: PageText) -> dict[int, str]:
        # 후보 줄 위치 → 정규화한 글자. 빈 줄·keep_patterns 줄은 후보가 아니다
        out = {}
        for i in _scan_indexes(len(page.lines), scan_lines):
            line = page.lines[i]
            if line.strip() and not is_kept(line):
                out[i] = _normalize(line)
        return out

    per_page = [candidates(p) for p in pages]

    # 쪽 수가 2 미만이면 되풀이를 판단할 수 없어 아무것도 안 뺀다
    if len(pages) < 2:
        return [PageText(page=p.page, lines=list(p.lines)) for p in pages], 0

    # 글자마다 몇 쪽에서 나왔는지 센다 (한 쪽에서 여러 번 나와도 한 번)
    page_count: dict[str, int] = {}
    for cand in per_page:
        for key in set(cand.values()):
            page_count[key] = page_count.get(key, 0) + 1

    need = max(2, math.ceil(min_page_ratio * len(pages)))
    repeated = {k for k, c in page_count.items() if c >= need}

    out_pages: list[PageText] = []
    removed = 0
    for page, cand in zip(pages, per_page, strict=True):
        drop = {i for i, key in cand.items() if key in repeated}
        removed += len(drop)
        out_pages.append(
            PageText(
                page=page.page,
                lines=[ln for i, ln in enumerate(page.lines) if i not in drop],
            )
        )
    return out_pages, removed
