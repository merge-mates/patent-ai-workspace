"""묶음 하나의 모델 호출 실패는 그 묶음만 보류한다 (이슈 #211, #166 (가)).

기록된 응답(FakeTransport)으로: 판단 단위 둘(진보성 c1, 명확성 c2) 중 하나가 실패하면
나머지 결과는 남고, 실패한 묶음은 보류 + 확인되지 않음 + 이유로 남는다.
모든 묶음이 실패하면 단계 전체가 못 돈 것이라 예외로 올린다 (지휘가 실행 failed로 끝낸다).
"""

import pytest

from patent_ai.core.llm.config import load_step_config
from patent_ai.core.llm.errors import ModelOutputInvalid
from patent_ai.core.llm.transport import TransportError, TransportResponse
from patent_ai.core.schemas.common import StatusValue, UnverifiedReason
from tests.core.f3 import scenario
from tests.core.f3.fakes import citation, claim_row, oa, rejection
from tests.core.f3.run_helpers import run_scenario

BAD_ANSWER = TransportResponse("대비 결과입니다", 100, 50)  # JSON이 아님 -> 출력 검사 실패
COMPARE_TASK = "f3_compare:oa_1:29-2:c1"
CLARITY_TASK = "f3_clarity:oa_1:42-4-2:c2"


def _held(result, task):
    return next((h for h in result.held_tasks if h.task == task), None)


def test_대비가_두_번_다_검사에_떨어져도_명확성_결과는_남고_대비_묶음만_보류한다():
    answers = scenario.responses()
    answers["f3.compare"] = [BAD_ANSWER, BAD_ANSWER]  # 첫 호출 + 한 번 더
    result, _ = run_scenario(answers=answers)
    assert result.comparisons == []
    assert [r.unit_id for r in result.clarity_reviews] == ["oa_1:42-4-2:c2"]
    held = _held(result, f"{COMPARE_TASK}:call_failed")
    assert held is not None
    assert held.waiting_for.startswith("원문 확인 필요")  # 보류 글자 (F3)
    assert "ModelOutputInvalid" in held.waiting_for  # 이유가 남는다
    # 조용히 성공으로 두지 않는다: 결과 전체가 확인되지 않음
    assert result.status.value == StatusValue.UNVERIFIED
    assert result.status.reason == UnverifiedReason.NOT_EXTRACTED


def test_명확성_검토가_전송_오류로_실패해도_대비표는_남고_명확성_묶음만_보류한다():
    answers = scenario.responses()
    answers["f3.clarity"] = [TransportError("연결 끊김", retryable=False)]
    result, _ = run_scenario(answers=answers)
    assert [t.unit_id for t in result.comparisons] == ["oa_1:29-2:c1"]
    assert result.clarity_reviews == []
    held = _held(result, f"{CLARITY_TASK}:call_failed")
    assert held is not None and "ModelCallFailed" in held.waiting_for
    assert result.status.value == StatusValue.UNVERIFIED


def test_모든_묶음이_실패하면_단계_전체가_못_돈_것이라_원래_예외를_그대로_올린다():
    answers = scenario.responses()
    answers["f3.compare"] = [BAD_ANSWER, BAD_ANSWER]
    answers["f3.clarity"] = [BAD_ANSWER, BAD_ANSWER]
    with pytest.raises(ModelOutputInvalid):
        run_scenario(answers=answers)


def test_프로그래밍_오류는_잡지_않고_그대로_올린다(monkeypatch):
    def broken(*args, **kwargs):
        raise TypeError("버그")

    monkeypatch.setattr("patent_ai.core.f3_claim_compare.compare.compare_unit", broken)
    with pytest.raises(TypeError):
        run_scenario()


def test_호출_상한에_닿으면_실패가_아니라_limit_reached로_보류하고_끝낸다():
    ctx, transport = scenario.context()
    cap = load_step_config("f3.compare").max_model_calls
    for _ in range(cap):  # 이 단계 호출을 상한만큼 이미 쓴 것으로 센다
        ctx.budget.add(ctx.run_id, "f3.compare", 0)
    result, _ = run_scenario(ctx=ctx, transport=transport)
    assert result.comparisons == []
    assert len(result.clarity_reviews) == 1  # 다른 단계(명확성)는 상한이 따로라 끝까지 한다
    held = _held(result, f"{COMPARE_TASK}:limit_reached")
    assert held is not None and "max_model_calls" in held.waiting_for
    assert result.status.value == StatusValue.UNVERIFIED
    assert result.status.reason == UnverifiedReason.LIMIT_REACHED


def test_대비가_실패해도_같은_단위에서_이미_나온_본문_미확보_보류는_남는다():
    # D3은 색인에 본문이 없어 `f3_compare:oa_1:D3` 보류가 먼저 나온다. 호출이 실패해도 버리지 않는다
    cited = [citation("D1", scenario.D1), citation("D3", "KR20990000009A")]
    result = oa(
        [rejection(1, "29-2", [1, 2], cited), rejection(2, "42-4-2", [2])],
        [claim_row(2, 2, clarity_terms=[scenario.MODULE])],
    )
    answers = scenario.responses()
    answers["f3.compare"] = [BAD_ANSWER, BAD_ANSWER]
    out, _ = run_scenario(oa=result, answers=answers)
    tasks = {h.task for h in out.held_tasks}
    assert "f3_compare:oa_1:D3" in tasks
    assert f"{COMPARE_TASK}:call_failed" in tasks


def _d3_only_and_d1_units():
    # 거절이유 1(신규성)은 D3만 인용(색인에 본문 없음 -> 모델을 부르기 전에 보류),
    # 거절이유 2(진보성)는 D1을 인용해 모델을 부른다. 명확성 단위는 없다
    d3 = [citation("D3", "KR20990000009A")]
    d1 = [citation("D1", scenario.D1)]
    return oa([rejection(1, "29-1-1", [1], d3), rejection(2, "29-2", [1, 2], d1)])


def test_모델을_부르기_전에_보류된_묶음은_분모에서_빼_모델을_부른_묶음이_모두_실패하면_올린다():
    # 리뷰(#251): 본문 없는 묶음 하나 + 모델 실패 묶음 하나면 실패가 묻히지 않고 실행 failed
    answers = scenario.responses()
    answers["f3.compare"] = [BAD_ANSWER, BAD_ANSWER]
    with pytest.raises(ModelOutputInvalid):
        run_scenario(oa=_d3_only_and_d1_units(), answers=answers)


def test_모델을_부르기_전에_보류된_묶음만_있으면_예외_없이_보류로_끝난다():
    # 모델을 부른 묶음이 0개면 "모두 실패"가 아니다: 본문 없음 보류 + 확인되지 않음으로 끝낸다
    d3 = [citation("D3", "KR20990000009A")]
    result = oa([rejection(1, "29-2", [1, 2], d3)])
    out, _ = run_scenario(oa=result)
    assert out.comparisons == []
    assert out.status.value == StatusValue.UNVERIFIED
    assert any(h.task == "f3_compare:oa_1:D3" for h in out.held_tasks)


def test_명확성_문구를_청구항에서_못_찾아_모델을_안_부른_묶음은_분모에서_뺀다():
    # 명확성 묶음은 짚은 문구가 청구항에 없어 모델을 부르지 않는다. 대비가 모두 실패하면 올린다
    result = oa(
        [
            rejection(1, "29-2", [1, 2], [citation("D1", scenario.D1)]),
            rejection(2, "42-4-2", [2]),
        ],
        [claim_row(2, 2, clarity_terms=["청구항에 없는 문구"])],
    )
    answers = scenario.responses()
    answers["f3.compare"] = [BAD_ANSWER, BAD_ANSWER]
    with pytest.raises(ModelOutputInvalid):
        run_scenario(oa=result, answers=answers)
