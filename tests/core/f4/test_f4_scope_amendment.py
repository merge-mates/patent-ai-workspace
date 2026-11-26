"""F4 보정 초안 단계의 보정 범위 테스트 (ADR 0005 결정 4, tasks.md m3-i2-scope-a task-4).

가짜 사건(case_basic): 청구항 1(독립항) · 2(1항 인용) · 3(1항 인용, 거절 대상 아님).
고른 방향이 "청구항 3의 특징을 1에 합치고 3 삭제"이면 보정 초안에 청구항 3의 `(삭제)`가 나와야 한다.
기대값은 ADR 0005 결정 4와 구현 계획 task-4 "테스트할 경우"에서 가져왔다. 진짜 모델 호출 없음.
"""

import copy
import json
from pathlib import Path

from patent_ai.core.f4_response_draft.inputs import F4Input
from patent_ai.core.f4_response_draft.run import run_f4
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "f4"


def _case() -> F4Input:
    data = json.loads((FIXTURES / "case_basic.json").read_text("utf-8"))
    data["spec"] = json.loads((FIXTURES / "spec_basic.pages.json").read_text("utf-8"))
    return F4Input.model_validate(data)


def _answer(name: str) -> dict:
    return json.loads((FIXTURES / "llm" / f"{name}.json").read_text("utf-8"))


def _text(answer: dict) -> TransportResponse:
    return TransportResponse(json.dumps(answer, ensure_ascii=False), 100, 50)


def _merge_and_delete_3() -> dict:
    answer = copy.deepcopy(_answer("direction_inventive"))
    answer["candidates"][0]["amendment_core"] = [
        {"claim": 1, "kind": "add", "source": "other_dependent"},
        {"claim": 3, "kind": "delete"},
    ]
    return answer


def _amend_1_and_delete_3() -> dict:
    answer = copy.deepcopy(_answer("amendment_inventive"))
    answer["claims"].append({"claim": 3, "text": "(삭제)", "spec_basis": []})
    return answer


def _run(amendments: list[dict]):
    transport = FakeTransport(
        {
            "f4.direction": [_text(_merge_and_delete_3()), _text(_answer("direction_clarity"))],
            "f4.opinion": [
                _text(_answer("opinion_inventive")),
                _text(_answer("opinion_clarity")),
            ],
            "f4.amendment": [_text(a) for a in amendments],
        }
    )
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    return run_f4(_case(), ctx=ctx), transport


def test_거절_대상이_아닌_종속항을_삭제하는_초안이_나온다():
    out, _ = _run([_amend_1_and_delete_3(), _answer("amendment_clarity")])
    by_claim = {c.claim: c for c in out.drafts.claims}
    assert by_claim[3].ai_text == "(삭제)"
    assert out.held_units == []


def test_보정_프롬프트에_보정_범위의_청구항_글자와_범위_블록이_들어간다():
    _, transport = _run([_amend_1_and_delete_3(), _answer("amendment_clarity")])
    prompts = [c["prompt"] for c in transport.calls if c["step"] == "f4.amendment"]
    assert "[청구항 3]" in prompts[0] and "범위만 넓힌 항" in prompts[0]


def test_보정_범위_밖_청구항을_고친_초안은_다시_불러도_틀리면_그_묶음만_보류():
    bad = copy.deepcopy(_amend_1_and_delete_3())
    bad["claims"].append({"claim": 9, "text": "없는 청구항", "spec_basis": []})
    out, _ = _run([bad, bad, _answer("amendment_clarity")])
    assert "oa_1:29-2:c1" in out.held_units
