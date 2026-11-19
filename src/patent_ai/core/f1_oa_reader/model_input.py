"""모델에 넣는 통지서 글자를 만든다 (이슈 #122 task-a, design.md 8절).

원본 PageText는 바꾸지 않는다. 원문 대조(verify)는 늘 원본 쪽 글자·표 칸으로 한다.
- raw: `[쪽 N]` + 쪽 글자 (전부터 쓰던 모양)
- tables_md: raw 각 쪽 뒤에 그 쪽에서 시작하는 표를 `[쪽 N 표]` 아래 마크다운으로 덧붙인다.
  표는 merged_tables(쪽을 넘은 거절이유 표 칸을 이어 붙인 것)라,
  쪽 글자에서 끊긴 칸도 한 칸으로 보인다.
  거절이유 표가 줄 사이에서 다음 쪽으로 넘어가면, 다음 쪽 표 앞에 앞 쪽 표의 머리 줄을 붙인다
  (안 붙이면 첫 데이터 줄이 마크다운 머리 줄로 읽힌다. PR #135 리뷰).
"""

from typing import Literal

from patent_ai.core.f1_oa_reader.tables import MergedTable, _is_head, _number, merged_tables
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


def _continued_head(previous: MergedTable | None, table: MergedTable) -> list[str] | None:
    """table이 앞 쪽 거절이유 표가 줄 사이에서 넘어온 것이면 앞 표의 머리 줄, 아니면 None.

    조건: 앞 표가 바로 앞 쪽의 마지막 표이고 머리 줄이 있음, table에 머리 줄이 없음,
    table 첫 줄 순번 = 앞 표 마지막 줄 순번 + 1 (tables.rejection_rows와 같은 이어짐 기준).
    """
    if previous is None or previous.page != table.page - 1 or not previous.last_on_page:
        return None
    if table.has_head or not previous.has_head:
        return None
    last_no = _number(previous.rows[-1][0]) if previous.rows[-1] else None
    first_no = _number(table.rows[0][0]) if table.rows[0] else None
    if last_no is None or first_no != last_no + 1:
        return None
    return next(row for row in previous.rows if _is_head(row))


def model_input(pages: PageText, mode: ModelInput) -> str:
    """모델 프롬프트의 $pages 자리에 넣을 글자."""
    if mode not in MODES:
        raise ValueError(f"model_input은 {MODES} 중 하나여야 함: {mode!r}")
    tables_by_page: dict[int, list[str]] = {}
    if mode == "tables_md":
        # 표는 시작한 쪽에 붙인다 (이어 붙인 조각은 다음 쪽 표로 다시 나오지 않음)
        previous: MergedTable | None = None
        for table in merged_tables(pages):
            if table.rows:
                # 그 쪽 첫 표일 때만 앞 쪽 표에서 이어졌는지 본다
                first_on_page = table.page not in tables_by_page
                head = _continued_head(previous, table) if first_on_page else None
                rows = [head, *table.rows] if head else table.rows
                tables_by_page.setdefault(table.page, []).append(_markdown(rows))
            previous = table
    blocks = []
    for p in pages.pages:
        block = f"[쪽 {p.page}]\n{p.text}"
        if p.page in tables_by_page:
            block += f"\n\n[쪽 {p.page} 표]\n" + "\n\n".join(tables_by_page[p.page])
        blocks.append(block)
    return "\n\n".join(blocks)
