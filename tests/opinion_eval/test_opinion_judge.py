"""의견서 저지 호출 모양 (가짜 전송층, 네트워크·키 없음).

system 칸, 논점 id 검사와 한 번 다시 부름.
"""

import json

import pytest

from eval.opinion.judge import AuxOut, judge_aux, judge_main
from patent_ai.core.llm.errors import ModelOutputInvalid
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse

MAIN_VARS = dict(
    issues="[]", oa_text="o", claims_at_oa="c", amendment="a", comparison="x", filed="f", draft="d"
)
AUX_VARS = {k: v for k, v in MAIN_VARS.items() if k != "filed"}


def issue(i, score=2):
    return {
        "id": i,
        "filed_point": "차이",
        "draft_point": "차이",
        "score": score,
        "reason": "같음",
        "evidence_check": "맞음",
    }


def ctx(fake):
    return RunContext(
        run_id="t", budget=CallBudget(), recorder=MemoryRecorder(), transport=fake, cache=False
    )


def resp(obj):
    return TransportResponse(json.dumps(obj, ensure_ascii=False), 10, 5)


def test_주_점수는_system을_보내고_논점마다_점수를_읽는다():
    fake = FakeTransport({"eval_judge.opinion_main": resp({"issues": [issue("A"), issue("B", 1)]})})
    out = judge_main(MAIN_VARS, ["A", "B"], ctx(fake)).parsed
    assert [i.score for i in out.issues] == [2, 1]
    assert "평가자" in fake.calls[0]["system"]
    assert "<filed>" in fake.calls[0]["prompt"]


def test_논점_id가_빠지면_한_번_다시_부르고_그래도_틀리면_예외():
    bad = resp({"issues": [issue("A")]})
    fake = FakeTransport({"eval_judge.opinion_main": [bad, bad]})
    with pytest.raises(ModelOutputInvalid):
        judge_main(MAIN_VARS, ["A", "B"], ctx(fake))
    assert len(fake.calls) == 2
    assert "검사 오류" in fake.calls[1]["prompt"] and "검사 오류" not in fake.calls[0]["prompt"]


def test_모델이_더_붙인_설명_칸은_버리고_읽는다():
    ans = {
        "c1": {"score": 2, "reason": "r", "missing": []},
        "c2": {"score": 1, "reason": "r", "missing": ["x"]},  # c2에는 없는 칸
        "c3": {"score": 1, "reason": "r", "major": 0, "minor": 2, "unverifiable": 1, "errors": []},
        "c5": {"score": 2, "reason": "r", "explained": 3, "changed": 3},
    }
    fake = FakeTransport({"eval_judge.opinion_aux": resp(ans)})
    assert judge_aux(AUX_VARS, ctx(fake)).parsed.c2.score == 1


def test_반박_논점이_0개면_부르지_않는다():
    fake = FakeTransport({})
    with pytest.raises(ValueError):
        judge_main(MAIN_VARS, [], ctx(fake))
    assert fake.calls == []


def test_보조_점수는_기준_네_개를_읽는다():
    ans = {
        "c1": {"score": 2, "reason": "r", "missing": []},
        "c2": {"score": 1, "reason": "r"},
        "c3": {"score": 1, "reason": "r", "major": 0, "minor": 2, "unverifiable": 1, "errors": []},
        "c5": {"score": 2, "reason": "r", "explained": 3, "changed": 3},
    }
    fake = FakeTransport({"eval_judge.opinion_aux": resp(ans)})
    out = judge_aux(AUX_VARS, ctx(fake)).parsed
    assert isinstance(out, AuxOut) and out.c3.minor == 2
    assert "<filed>" not in fake.calls[0]["prompt"]
