"""넘긴 단계 -> 경고 만들기 규칙 (이슈 #57 T5)."""

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
