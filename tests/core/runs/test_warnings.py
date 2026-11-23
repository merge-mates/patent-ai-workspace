"""넘긴 단계 -> 경고 만들기 규칙 (이슈 #57 T5)."""

from patent_ai.core.runs.store import SkippedStep
from patent_ai.core.runs.warnings import RunWarning, skipped_step_warnings


def test_넘긴_단계마다_step_skipped_경고가_하나씩_생긴다():
    skipped = [SkippedStep("인용문헌 조회", "자료 없음"), SkippedStep("법령 조회", "도구 없음")]
    assert skipped_step_warnings(skipped) == [
        RunWarning("step_skipped", "인용문헌 조회 단계를 건너뜀: 자료 없음"),
        RunWarning("step_skipped", "법령 조회 단계를 건너뜀: 도구 없음"),
    ]


def test_넘긴_단계가_없으면_빈_목록():
    assert skipped_step_warnings([]) == []


def test_호출_상한_이유는_limit_reached_경고_코드가_된다():
    reason = "limit_reached: 지휘 호출 상한 max_model_calls 2에 닿음"
    assert [w.code for w in skipped_step_warnings([SkippedStep("decide", reason)])] == [
        "limit_reached"
    ]
