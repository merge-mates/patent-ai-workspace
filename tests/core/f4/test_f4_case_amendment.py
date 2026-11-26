"""사건 단위 보정안(E) 단계 테스트: 가짜 전송층, 진짜 모델 호출 없음.

기대값은 11/26 은진 지시(앱 화면에서 보정안·의견서까지 끝까지)와 합친 흐름 실험 카드에서 가져왔다:
- amendment_enabled false이고 바깥 보정 결과가 없으면,
  F4가 사건 한 번에 보정안을 만든다 (f4.case_amendment)
- 그 프롬프트에는 OA 글자 전체, 청구항 전체, 출원서 글자가 들어간다
- 보정안 1번 안을 바깥 보정 결과로 옮겨 의견서(묶음 반박 + 사건 한 번)가 쓴다
- 보정안은 초안의 보정 청구항 칸(drafts.claims)에 실리고, 코드 검사 표시와 전략 글이 결과에 남는다
- 바깥 보정 결과를 이미 받았으면 보정안 단계를 부르지 않는다
"""

import dataclasses

from test_f4_opinion_v2 import CASE_WITH, ORACLE, UNIT_OUT, _answer, _case, _resp

from patent_ai.core.f4_response_draft.config import load_f4_options
from patent_ai.core.f4_response_draft.inputs import F4Input
from patent_ai.core.f4_response_draft.run import run_f4
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport

OK = {"value": "confirmed", "checked": "원문 대조"}
OA_PAGES = {
    "document_id": "doc_oa",
    "pages": [{"page": 1, "text": "OA 원문 표시글: 청구항 2는 인용발명 1과 같다.", "status": OK}],
    "status": OK,
}
NEW_1 = (
    "기판 위에 놓인 센서와, 상기 센서를 덮는 투명 덮개와, "
    "상기 덮개에 김 서림 방지 막을 포함하는 가상의 센서 장치."
)
DRAFT = {
    "strategy": "제3항의 김 서림 방지 막을 제1항에 합치고 제3항을 지운다.",
    "amended": [
        {
            "claim": 1,
            "action": "amend",
            "text": NEW_1,
            "confidence": 80,
            "reason": "합침",
            "merged_into": [],
        },
        {
            "claim": 3,
            "action": "delete",
            "text": "",
            "confidence": 80,
            "reason": "1항에 합침",
            "merged_into": [1],
        },
    ],
}
E_OUT = {"table": [], "drafts": [DRAFT, DRAFT, DRAFT]}


def _run(with_external=False):
    t = FakeTransport(
        {
            "f4.case_amendment": [_resp(E_OUT)],
            "f4.direction": [_answer("direction_inventive"), _answer("direction_clarity")],
            "f4.opinion_unit": [_resp(UNIT_OUT), _resp(UNIT_OUT)],
            "f4.opinion_case": [_resp(CASE_WITH)],
        }
    )
    ctx = RunContext(run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=t)
    data = _case(ORACLE if with_external else None)
    data["oa_pages"] = OA_PAGES
    options = dataclasses.replace(
        load_f4_options(), amendment_enabled=False, case_amendment_enabled=True
    )
    return run_f4(F4Input.model_validate(data), ctx=ctx, options=options), t


def test_바깥_보정_결과가_없으면_사건_한_번에_보정안을_만든다():
    _, t = _run()
    calls = [c for c in t.calls if c["step"] == "f4.case_amendment"]
    assert len(calls) == 1
    prompt = calls[0]["prompt"]
    assert "OA 원문 표시글" in prompt
    assert "김 서림 방지 막을 둔 가상의 센서 장치" in prompt  # OA 당시 청구항 3 글
    assert "이 문서는 테스트용으로 지어낸 명세서이다" in prompt  # 출원서 글자


def test_보정안이_의견서_입력과_보정_청구항_칸에_들어간다():
    out, t = _run()
    unit = [c for c in t.calls if c["step"] == "f4.opinion_unit"][0]["prompt"]
    assert NEW_1 in unit
    claims = {c.claim: c for c in out.drafts.claims}
    assert claims[1].ai_text == NEW_1 and claims[3].ai_text == "(삭제)"
    assert claims[1].before.startswith("기판 위에 놓인 센서와")
    assert out.amendment_strategy == DRAFT["strategy"]
    assert isinstance(out.amendment_checks, list)


def test_바깥_보정_결과를_받았으면_보정안_단계를_부르지_않는다():
    _, t = _run(with_external=True)
    assert not [c for c in t.calls if c["step"] == "f4.case_amendment"]
