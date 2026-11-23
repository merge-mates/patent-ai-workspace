"""실행 경고 만들기 (이슈 #57 T5). 라우터는 이 함수를 부르기만 한다."""

from dataclasses import dataclass

from patent_ai.core.runs.store import SkippedStep


@dataclass(frozen=True)
class RunWarning:
    code: str
    message: str


def skipped_step_warnings(skipped: list[SkippedStep]) -> list[RunWarning]:
    """넘긴 단계마다 경고 하나. 실행은 계속되니 사람이 빠진 부분을 알아보게 한다."""
    return [
        RunWarning(
            # 호출 상한에 닿아 넘긴 단계는 코드를 따로 준다 (이유는 orchestrator.limit_reason)
            "limit_reached" if s.reason.startswith("limit_reached:") else "step_skipped",
            f"{s.step} 단계를 건너뜀: {s.reason}",
        )
        for s in skipped
    ]
