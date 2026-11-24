"""F4 방향 후보 단계의 보정 범위 테스트 (ADR 0005 결정 3·4·7, tasks.md m3-i2-scope-a task-3).

가짜 사건(case_basic): 청구항 1(독립항) · 2(1항 인용) · 3(1항 인용).
진보성 묶음 c1의 거절 대상은 1·2이고 청구항 3은 거절 대상이 아니다
→ 보정 범위 [1, 2, 3], 넓힌 항 [3].
명확성 묶음 c2(대상 2, 함께 읽을 1)는 넓히지 않는다.
기대값은 ADR 0005 결정 2~4와 구현 계획 task-3 "테스트할 경우"에서 가져왔다. 진짜 모델 호출 없음.
"""

import copy
import json
from pathlib import Path

from patent_ai.core.f4_response_draft.directions import STEP, build_directions
from patent_ai.core.f4_response_draft.inputs import F4Input
from patent_ai.core.f4_response_draft.run import run_f4
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "f4"
UNIT_INVENTIVE = "oa_1:29-2:c1"
UNIT_CLARITY = "oa_1:42-4-2:c2"


def _case_data() -> dict:
    data = json.loads((FIXTURES / "case_basic.json").read_text("utf-8"))
    data["spec"] = json.loads((FIXTURES / "spec_basic.pages.json").read_text("utf-8"))
    return data


def _answer(name: str) -> dict:
    return json.loads((FIXTURES / "llm" / f"{name}.json").read_text("utf-8"))


def _text(answer: dict) -> TransportResponse:
    return TransportResponse(json.dumps(answer, ensure_ascii=False), 100, 50)


def _ctx(responses: dict) -> tuple[RunContext, FakeTransport]:
    transport = FakeTransport(responses)
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    return ctx, transport


def _merge_and_delete_3() -> dict:
    """청구항 3(거절 대상 아님)의 특징을 1에 합치고 3을 삭제하는 답 (실제 보정서에서 흔한 꼴)."""
    answer = copy.deepcopy(_answer("direction_inventive"))
    answer["candidates"][0]["amendment_core"] = [
        {"claim": 1, "kind": "add", "source": "other_dependent"},
        {"claim": 3, "kind": "delete"},
    ]
    return answer


def _with_claim(answer: dict, claim: int) -> dict:
    out = copy.deepcopy(answer)
    out["candidates"][0]["amendment_core"].append({"claim": claim, "kind": "clarify"})
    return out


def test_거절_대상이_아닌_종속항을_합치고_삭제하는_답이_통과한다():
    ctx, _ = _ctx({STEP: [_text(_merge_and_delete_3()), _text(_answer("direction_clarity"))]})
    results = build_directions(F4Input.model_validate(_case_data()), ctx)
    first = results[0].candidates[0]
    assert [(a.claim, a.kind) for a in first.amendment_core] == [(1, "add"), (3, "delete")]


def test_방향_프롬프트에_보정_범위의_청구항_글자와_범위_블록이_들어간다():
    ctx, transport = _ctx(
        {STEP: [_text(_answer("direction_inventive")), _text(_answer("direction_clarity"))]}
    )
    build_directions(F4Input.model_validate(_case_data()), ctx)
    inventive, clarity = (c["prompt"] for c in transport.calls)
    assert "[청구항 3]" in inventive
    assert "보정 범위" in inventive and "범위만 넓힌 항" in inventive
    # 명확성 묶음은 넓히지 않는다: 대상 2와 함께 읽을 1만
    assert "[청구항 3]" not in clarity


def test_보정_범위_밖_청구항을_쓴_답은_출력_검사에_떨어져_그_묶음만_보류된다():
    bad = _with_claim(_answer("direction_inventive"), 9)  # 9는 OA에 없는 항 = 범위 밖
    ctx, _ = _ctx({STEP: [_text(bad), _text(bad), _text(_answer("direction_clarity"))]})
    results = build_directions(F4Input.model_validate(_case_data()), ctx)
    assert results[0].candidates == [] and results[0].needs_recheck
    assert results[1].candidates  # 다른 묶음은 그대로


def test_명확성_묶음은_넓히지_않아_청구항_3을_쓰면_떨어진다():
    bad = _with_claim(_answer("direction_clarity"), 3)
    ctx, _ = _ctx({STEP: [_text(_answer("direction_inventive")), _text(bad), _text(bad)]})
    results = build_directions(F4Input.model_validate(_case_data()), ctx)
    assert results[1].candidates == [] and results[1].needs_recheck


def test_실행_결과에_묶음마다_넓힌_항이_남는다():
    ctx, _ = _ctx(
        {
            "f4.direction": [
                _text(_answer("direction_inventive")),
                _text(_answer("direction_clarity")),
            ],
            "f4.opinion": [
                _text(_answer("opinion_inventive")),
                _text(_answer("opinion_clarity")),
            ],
            "f4.amendment": [
                _text(_answer("amendment_inventive")),
                _text(_answer("amendment_clarity")),
            ],
        }
    )
    out = run_f4(F4Input.model_validate(_case_data()), ctx=ctx)
    assert out.amendment_scopes == {UNIT_INVENTIVE: [3], UNIT_CLARITY: []}
