"""원문 위치 대조: 값의 원문 글자가 붙은 쪽 글자에 실제로 있나.

requirements 9번 '확인하지 않은 원문 위치'를 셀 때 쓴다.

앱 원문 대조(f1_oa_reader/verify.py raw_text_on_page, #125)와 같은 규칙이어야 한다.
다르면 앱이 확인한 값이 채점에서 가짜로 '확인하지 않은 위치'가 되거나 그 반대가 된다.
찾는 순서:
1) 그 쪽 글자 (공백·줄바꿈만 무시)
2) 그 쪽에서 시작하는 표 칸 (다음 쪽으로 넘어간 칸은 이어 붙인 것, cells_from_page)
3) 그 쪽 + 다음 쪽 본문을 이어 붙여 찾되, 찾은 글자의 시작이 앞 쪽 안이어야 한다.
   본문은 쪽마다 첫 줄 출원번호 머리말·끝 줄 쪽 번호 꼬리말을 뺀 것.
#125가 main에 들어가면 이 파일 대신 raw_text_on_page를 같이 쓸지 다시 본다.
"""

import re

from patent_ai.core.f1_oa_reader.tables import cells_from_page
from patent_ai.core.schemas.document import PageText

# #125 verify.py와 같은 꼴 (tune OA에서 쪽마다 첫 줄이 출원번호, 끝 줄이 쪽 번호)
_RUNNING_HEADER = re.compile(r"\d{2}-\d{4}-\d{7}")  # 첫 줄: 출원번호만 있는 줄
_RUNNING_FOOTER = re.compile(r"-\s*\d+\s*-|\d+\s*/\s*\d+")  # 끝 줄: `- 3 -` 또는 `3/6`


def _squash(text: str) -> str:
    return "".join(text.split())


def _body(text: str) -> str:
    """쪽 글자에서 첫 줄 머리말·끝 줄 꼬리말만 뺀 본문 (가운데 줄은 그대로)."""
    lines = [line for line in text.splitlines() if line.strip()]
    if lines and _RUNNING_HEADER.fullmatch(lines[0].strip()):
        lines = lines[1:]
    if lines and _RUNNING_FOOTER.fullmatch(lines[-1].strip()):
        lines = lines[:-1]
    return "\n".join(lines)


def text_on_page(pages: PageText, page: int | None, text: str) -> bool:
    """text가 page 쪽(두 쪽에 걸치면 시작 쪽)에 실제로 있나. 없는 쪽·빈 글자는 False."""
    needle = _squash(text)
    if not needle or page is None:
        return False
    by_page = {p.page: p for p in pages.pages}
    if page not in by_page:
        return False
    if needle in _squash(by_page[page].text):
        return True
    if any(needle in _squash(cell) for cell in cells_from_page(pages, page)):
        return True
    if page + 1 not in by_page:
        return False  # 마지막 쪽이면 이어 볼 쪽이 없다
    head = _squash(_body(by_page[page].text))
    joined = head + _squash(_body(by_page[page + 1].text))
    at = joined.find(needle)  # 처음 나온 자리
    return 0 <= at < len(head)  # 통째로 다음 쪽에만 있으면 앞 쪽 번호로는 안 됨
