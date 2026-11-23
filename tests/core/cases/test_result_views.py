"""결과가 빈 이유 글 (#241·#331 리뷰). 확인: uv run pytest tests/core/cases/test_result_views.py"""

import pytest

from patent_ai.core.cases.result_views import _why_missing
from patent_ai.core.runs.store import SkippedStep


class _Runs:
    def __init__(self, reason: str) -> None:
        self._reason = reason

    def skipped_steps(self, run_id):
        return [SkippedStep("run_f3", self._reason)]


@pytest.mark.parametrize(
    ("reason", "want"),
    [
        (
            "limit_reached: decide 호출 상한 max_model_calls 2에 닿음",
            "확인되지 않음: decide 호출 상한 max_model_calls 2에 닿음",
        ),
        ("input_unverified: 글자 없음", "넘김: input_unverified: 글자 없음"),
    ],
)
def test_상한으로_못_돈_단계는_넘김이_아니라_확인되지_않음(reason, want):
    assert _why_missing("run_f3", "r_1", _Runs(reason)) == want
