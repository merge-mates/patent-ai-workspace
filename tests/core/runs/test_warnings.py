"""넘긴 단계 -> 경고 만들기 규칙 (이슈 #57 T5)."""

from patent_ai.core.agents.orchestrator import limit_reason
from patent_ai.core.llm.errors import ModelCallLimitExceeded
from patent_ai.core.runs.store import SkippedStep
from patent_ai.core.runs.warnings import RunWarning, skipped_step_warnings


def test_넘긴_단계마다_step_skipped_경고가_하나씩_생긴다():
    skipped = [SkippedStep("run_f3", "자료 없음"), SkippedStep("run_f2", "도구 없음")]
    assert skipped_step_warnings(skipped) == [
        RunWarning("step_skipped", "run_f3 단계를 건너뜀: 자료 없음"),
        RunWarning("step_skipped", "run_f2 단계를 건너뜀: 도구 없음"),
    ]


def test_넘긴_단계가_없으면_빈_목록():
    assert skipped_step_warnings([]) == []


def test_호출_상한_이유는_limit_reached_경고_코드가_된다():
    reason = limit_reason("decide", ModelCallLimitExceeded("max_model_calls", 3, 2))
    (w,) = skipped_step_warnings([SkippedStep("run_f3", reason)])
    assert w.code == "limit_reached"
    # 건너뜀과 구분되는 글: 앞머리 코드는 떼고 단계·상한만
    assert (
        w.message
        == "run_f3 단계를 호출 상한으로 못 돌림: decide 호출 상한 max_model_calls 2에 닿음"
    )
