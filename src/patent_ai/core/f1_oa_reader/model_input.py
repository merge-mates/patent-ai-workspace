"""모델에 넣는 통지서 글자를 만든다 (이슈 #122 task-a, design.md 8절).

원본 PageText는 바꾸지 않는다. 원문 대조(verify)는 늘 원본 쪽 글자·표 칸으로 한다.
- raw: `[쪽 N]` + 쪽 글자 (전부터 쓰던 모양)
- tables_md: raw 각 쪽 뒤에 그 쪽에서 시작하는 표를 `[쪽 N 표]` 아래 마크다운으로 덧붙인다.
  표는 merged_tables(쪽을 넘은 거절이유 표 칸을 이어 붙인 것)라,
  쪽 글자에서 끊긴 칸도 한 칸으로 보인다.
"""

from typing import Literal

from patent_ai.core.f1_oa_reader.tables import merged_tables
from patent_ai.core.schemas.document import PageText

ModelInput = Literal["raw", "tables_md"]
MODES: tuple[str, ...] = ("raw", "tables_md")


def _cell(text: str) -> str:
    """칸 글자: 줄바꿈·겹친 공백은 공백 하나로, 칸 구분 `|`는 `\\|`로."""
    return " ".join(text.split()).replace("|", "\\|")


def _markdown(rows: list[list[str]]) -> str:
    """표 하나를 마크다운으로. 첫 줄을 머리 줄로 두고, 칸이 모자란 줄은 빈 칸으로 채운다."""
    width = max(len(row) for row in rows)

    def line(row: list[str]) -> str:
        cells = [_cell(c) for c in row] + [""] * (width - len(row))
        return "| " + " | ".join(cells) + " |"

    return "\n".join([line(rows[0]), "|" + "---|" * width] + [line(row) for row in rows[1:]])


def model_input(pages: PageText, mode: ModelInput) -> str:
    """모델 프롬프트의 $pages 자리에 넣을 글자."""
    if mode not in MODES:
        raise ValueError(f"model_input은 {MODES} 중 하나여야 함: {mode!r}")
    tables_by_page: dict[int, list[str]] = {}
    if mode == "tables_md":
        # 표는 시작한 쪽에 붙인다 (이어 붙인 조각은 다음 쪽 표로 다시 나오지 않음)
        for table in merged_tables(pages):
            if table.rows:
                tables_by_page.setdefault(table.page, []).append(_markdown(table.rows))
    blocks = []
    for p in pages.pages:
        block = f"[쪽 {p.page}]\n{p.text}"
        if p.page in tables_by_page:
            block += f"\n\n[쪽 {p.page} 표]\n" + "\n\n".join(tables_by_page[p.page])
        blocks.append(block)
    return "\n\n".join(blocks)
