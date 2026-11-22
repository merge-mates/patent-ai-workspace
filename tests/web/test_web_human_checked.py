"""화면이 "직접 입력" 꼬리표를 다는 글자가 서버 HUMAN_CHECKED와 같은지 본다 (#269 리뷰).

한쪽만 바뀌면 사람이 넣은 번호가 화면에서 AI 값처럼 보인다 (꼬리표는 같은 글자일 때만 붙음).
"""

import re
from pathlib import Path

from patent_ai.core.cases.human_answers import HUMAN_CHECKED

LABELS = Path(__file__).resolve().parents[2] / "web" / "src" / "labels.ts"


def test_화면_직접_입력_글자는_서버_HUMAN_CHECKED와_같다():
    m = re.search(r"export const HUMAN_ENTERED_CHECKED = '([^']*)'", LABELS.read_text("utf-8"))
    assert m, "web/src/labels.ts에 HUMAN_ENTERED_CHECKED가 없다"
    assert m.group(1) == HUMAN_CHECKED
