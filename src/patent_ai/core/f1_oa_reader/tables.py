"""쪽을 넘어간 표 칸 이어 붙이기와 거절이유 표 줄 읽기 (task-8, 코드 규칙. 모델 안 씀).

OA 1쪽 아래 거절이유 표(순번 / 거절이유가 있는 부분 / 관련 법조항)는 2쪽으로 넘어갈 때가 있다.
칸 하나가 쪽 중간에서 잘리면 다음 쪽 첫 표의 첫 줄이 순번 칸이 빈 ['', '<나머지>', ''] 모양이 된다.
"""

import re
from dataclasses import dataclass, replace

from patent_ai.core.schemas.document import PageText

# 청구항 목록이 이어지는 말.
# 칸이 목록 중간에서 잘렸다면 잘린 앞 끝이나 이어지는 앞머리에 이것이 있다
_JOIN_END = re.compile(r"(내지|,|및|~|-|와|과)$")
_JOIN_START = re.compile(r"^(내지|,|및|~|-)")


def _squash(text: str) -> str:
    return "".join(text.split())


def _is_head(row: list[str]) -> bool:
    """거절이유 표 머리 줄인가 (칸 글자 사이에 공백·줄바꿈이 끼어도 찾는다)."""
    return len(row) >= 3 and _squash(row[0]) == "순번" and "거절이유가있는부분" in _squash(row[1])


@dataclass
class MergedTable:
    """쪽을 넘어간 칸을 이어 붙인 표 하나.

    page: 표가 시작한 쪽. last_on_page: 그 쪽의 마지막 표인가.
    continued: 다음 쪽 첫 줄(순번 빈칸)을 이 표 마지막 줄에 붙였나.
    """

    page: int
    rows: list[list[str]]
    last_on_page: bool
    continued: bool = False

    @property
    def has_head(self) -> bool:
        return any(_is_head(row) for row in self.rows)


@dataclass(frozen=True)
class RejectionRow:
    """거절이유 표 한 줄. page는 그 줄이 시작한 쪽 (칸이 다음 쪽으로 넘어가도).

    may_be_cut: 그 쪽 마지막 표의 마지막 줄인데 다음 쪽에서 이어지는 조각을 못 찾음.
    칸이 잘렸는데 조각이 표로 안 잡혔을 수 있어, 이 줄 값은 규칙 쪽 값으로 쓰지 않는다.
    """

    no: int
    page: int
    part: str  # 거절이유가 있는 부분 (대상 청구항 등)
    article: str  # 관련 법조항
    may_be_cut: bool = False


def _number(cell: str) -> int | None:
    s = _squash(cell)
    return int(s) if s.isdigit() else None


def _is_fragment(previous: MergedTable, first_row: list[str]) -> bool:
    """다음 쪽 첫 표의 첫 줄이 앞 쪽 거절이유 표 마지막 칸의 잘린 나머지인가.

    1) 앞 표가 그 쪽 마지막 표이고 거절이유 표(머리 줄 있음)
    2) 첫 칸(순번)이 비고 칸 수가 같음
    3) 채워진 칸마다 앞 칸 끝이나 조각 앞머리에 목록 이음말이 있음 (목록 중간에서 잘린 흔적)
    """
    last = previous.rows[-1]
    if not (previous.last_on_page and previous.has_head):
        return False
    if first_row[0].strip() or len(first_row) != len(last):
        return False
    filled = [(col, cell) for col, cell in enumerate(first_row) if cell.strip()]
    if not filled:
        return False
    return all(
        _JOIN_END.search(_squash(last[col])) or _JOIN_START.search(_squash(cell))
        for col, cell in filled
    )


def merged_tables(pages: PageText) -> list[MergedTable]:
    """쪽마다 표를 펼치고, 쪽을 넘어간 거절이유 표 칸을 이어 붙인다 (빈 칸은 붙이지 않는다)."""
    merged: list[MergedTable] = []
    previous_page = None  # 앞 쪽 번호 (그 쪽에 표가 있었을 때만 마지막 표가 merged[-1])
    for page in pages.pages:
        for i, table in enumerate(page.tables):
            rows = [list(row) for row in table]
            last_on_page = i == len(page.tables) - 1
            if (
                i == 0
                and rows
                and merged
                and previous_page == page.page - 1
                and merged[-1].page <= page.page - 1
                and _is_fragment(merged[-1], rows[0])
            ):
                target = merged[-1].rows[-1]
                for col, cell in enumerate(rows[0]):
                    if cell.strip():
                        target[col] = f"{target[col]} {cell.strip()}".strip()
                merged[-1].continued = True
                rows = rows[1:]
            if rows:
                merged.append(MergedTable(page=page.page, rows=rows, last_on_page=last_on_page))
            elif last_on_page and merged:
                merged[-1].last_on_page = True  # 조각만 있던 표: 앞 표가 이 쪽 끝까지 이어짐
        previous_page = page.page if page.tables else None
    return merged


def rejection_rows(pages: PageText) -> list[RejectionRow]:
    """거절이유 표 줄들. 머리 줄 뒤 순번이 1씩 이어지는 줄만 (다음 쪽 첫 표로 이어지면 그 줄도)."""
    tables = merged_tables(pages)
    last_page = pages.pages[-1].page if pages.pages else 0
    for index, table in enumerate(tables):
        head = next((k for k, row in enumerate(table.rows) if _is_head(row)), None)
        if head is None:
            continue
        # 1) 머리 줄이 있는 표의 줄들, 2) 줄 사이에서 쪽이 끊기면 다음 쪽 첫 표의 줄들도 후보
        sources = [(table, table.rows[head + 1 :])]
        if index + 1 < len(tables) and tables[index + 1].page == table.page + 1:
            sources.append((tables[index + 1], tables[index + 1].rows))
        rows: list[RejectionRow] = []
        for source, source_rows in sources:
            for k, row in enumerate(source_rows):
                no = _number(row[0]) if len(row) >= 3 else None
                if no is None or (rows and no != rows[-1].no + 1):
                    return rows  # 순번이 없거나 1씩 이어지지 않으면 표가 끝난 것
                if rows and rows[-1].may_be_cut and source.page != rows[-1].page:
                    # 다음 쪽 첫 줄이 다음 순번이면 앞 줄은 줄 사이에서 끊긴 것 (잘리지 않음)
                    rows[-1] = replace(rows[-1], may_be_cut=False)
                # 그 쪽 마지막 표의 마지막 줄인데 다음 쪽 조각을 못 붙였으면 잘렸을 수 있음
                cut = (
                    k == len(source_rows) - 1
                    and source.last_on_page
                    and not source.continued
                    and source.page < last_page
                )
                rows.append(
                    RejectionRow(
                        no=no, page=source.page, part=row[1], article=row[2], may_be_cut=cut
                    )
                )
        return rows  # 거절이유 표는 OA에 하나
    return []


def cells_from_page(pages: PageText, page: int) -> list[str]:
    """그 쪽에서 시작하는 (이어 붙인) 표 칸 글자들. 원문 대조가 쓴다."""
    return [cell for t in merged_tables(pages) if t.page == page for row in t.rows for cell in row]
