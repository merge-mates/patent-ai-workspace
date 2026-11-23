"""실행 경고 만들기 (이슈 #57 T5). 라우터는 이 함수를 부르기만 한다."""

from dataclasses import dataclass

from patent_ai.core.agents.steps import LIMIT_PREFIX
from patent_ai.core.runs.store import SkippedStep


def is_limit_reason(reason: str) -> bool:
    return reason.startswith(LIMIT_PREFIX)


@dataclass(frozen=True)
class RunWarning:
    code: str
    message: str


def skipped_step_warnings(skipped: list[SkippedStep]) -> list[RunWarning]:
    """넘긴 단계마다 경고 하나. 실행은 계속되니 사람이 빠진 부분을 알아보게 한다."""
    out = []
    for s in skipped:
        if is_limit_reason(s.reason):
            # 호출 상한에 닿아 못 돌린 단계는 건너뜀과 구분한다 (이유는 orchestrator.limit_reason)
            text = s.reason.removeprefix(LIMIT_PREFIX)
            out.append(
                RunWarning("limit_reached", f"{s.step} 단계를 호출 상한으로 못 돌림: {text}")
            )
        else:
            out.append(RunWarning("step_skipped", f"{s.step} 단계를 건너뜀: {s.reason}"))
    return out
