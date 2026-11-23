"""넘김 이유 글: 앞머리 코드는 두고, 뒤 글에는 코드 이름이 없다 (이슈 #294).

화면(web/src/components/EmptyReason.tsx)은 앞머리 "input_unverified:"만 한국어로 바꾸고
뒤 글은 그대로 보인다. 그래서 뒤 글에 (CaseInput.texts)·(read_oa) 같은 코드 이름이 있으면 안 된다.
"""

import re
from datetime import date

import pytest

from patent_ai.core.agents.step_inputs import InputMissing, f2_input, f3_input, f4_input
from patent_ai.core.f3_claim_compare.inputs import F3Inputs
from patent_ai.core.f3_claim_compare.result import F3Result
from patent_ai.core.schemas.oa_result import OAResult

# 검사에 필요한 건 타입뿐이라 칸 검사 없이 만든다
OA = OAResult.model_construct()
F3 = F3Result.model_construct()
TEXTS = F3Inputs.model_construct()
DAY = date(2026, 11, 1)

# 코드 이름 모양: 소문자·밑줄 이어진 이름(read_oa, run_f3), 점으로 이은 이름(CaseInput.texts)
CODE_NAME = re.compile(r"[a-z_]{3,}|[A-Za-z]+\.[A-Za-z]+")

CASES = {
    "f3 OA 정리 없음": lambda: f3_input({}, "c_1", TEXTS),
    "f3 글자 없음": lambda: f3_input({"read_oa": OA}, "c_1", None),
    "f2 OA 정리 없음": lambda: f2_input({"run_f3": F3}, DAY),
    "f2 F3 없음": lambda: f2_input({"read_oa": OA}, DAY),
    "f2 기준일 없음": lambda: f2_input({"read_oa": OA, "run_f3": F3}, None),
    "f4 OA 정리 없음": lambda: f4_input({"run_f3": F3}, TEXTS, DAY),
    "f4 F3 없음": lambda: f4_input({"read_oa": OA}, TEXTS, DAY),
    "f4 글자 없음": lambda: f4_input({"read_oa": OA, "run_f3": F3}, None, DAY),
    "f4 기준일 없음": lambda: f4_input({"read_oa": OA, "run_f3": F3}, TEXTS, None),
}


@pytest.mark.parametrize("name", CASES)
def test_넘김_이유는_앞머리_코드_뒤에_사람이_읽는_말만(name):
    out = CASES[name]()
    assert isinstance(out, InputMissing), name
    head, body = out.why.split(": ", 1)
    assert head == "input_unverified"
    assert body and not CODE_NAME.search(body), body
