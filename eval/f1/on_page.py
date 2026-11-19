"""원문 위치 대조: 값의 원문 글자가 붙은 쪽 글자에 실제로 있나.

requirements 9번 '확인하지 않은 원문 위치'를 셀 때 쓴다.

앱 원문 대조(f1_oa_reader/verify.py raw_text_on_page, #125)를 그대로 부른다. 규칙을 두 곳에 두면
한쪽만 바뀌어 앱이 확인한 값이 채점에서 가짜로 '확인하지 않은 위치'가 될 수 있어서다.
규칙(앱 쪽): 그 쪽 글자 -> 그 쪽에서 시작하는 (이어 붙인) 표 칸 -> 그 쪽 + 다음 쪽 본문
(머리말·꼬리말 뺌)을 이어 붙여 찾되 시작이 앞 쪽이어야 한다.
이 약속은 tests/f1_eval/test_f1_on_page.py가 지킨다.
"""

from patent_ai.core.f1_oa_reader.verify import raw_text_on_page
from patent_ai.core.schemas.document import PageText


def text_on_page(pages: PageText, page: int | None, text: str) -> bool:
    """text가 page 쪽(두 쪽에 걸치면 시작 쪽)에 실제로 있나. 쪽이 없으면(None) False."""
    if page is None:
        return False  # 쪽을 안 낸 값은 확인할 곳이 없다 (앱 함수는 쪽 번호를 받는다)
    return raw_text_on_page(pages, page, text)
