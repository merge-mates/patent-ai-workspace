"""호출 상한 세기와 호출 기록. 상태는 객체(CallBudget·MemoryRecorder)에 두고 call_model에 넘긴다."""

import logging
from dataclasses import dataclass
from typing import Protocol

from patent_ai.core.llm.errors import ModelCallLimitExceeded

logger = logging.getLogger(__name__)


class CallBudget:
    """실행(run_id)·단계(step)마다 쓴 호출 수와 입력 토큰 수를 센다.

    인자로 안 넘기면 call_model이 모듈 공용 객체(DEFAULT_BUDGET)를 쓴다.
    테스트는 새 CallBudget()을 만들어 넘기거나 reset()을 부른다.
    """

    def __init__(self) -> None:
        self._calls: dict[tuple[str, str], int] = {}
        self._tokens: dict[tuple[str, str], int] = {}
        self._warned: set[tuple[str, str]] = set()

    def reset(self) -> None:
        self.__init__()

    def check(
        self, run_id: str, step: str, max_calls: int | None, max_input_tokens: int | None
    ) -> None:
        """전송층을 부르기 직전에 부른다. 이미 상한만큼 썼으면 예외."""
        key = (run_id, step)
        if max_calls is None and max_input_tokens is None and key not in self._warned:
            self._warned.add(key)
            logger.warning("%s: 호출 상한 설정이 없어 제한 없이 부름 (run_id=%s)", step, run_id)
        used_calls = self._calls.get(key, 0)
        if max_calls is not None and used_calls >= max_calls:
            raise ModelCallLimitExceeded("max_model_calls", used_calls, max_calls)
        used_tokens = self._tokens.get(key, 0)
        # 입력 토큰은 부르기 전엔 모르니, 지금까지 쓴 양이 상한에 닿았으면 막는다
        if max_input_tokens is not None and used_tokens >= max_input_tokens:
            raise ModelCallLimitExceeded("max_input_tokens", used_tokens, max_input_tokens)

    def add(self, run_id: str, step: str, input_tokens: int) -> None:
        """전송층을 부른 뒤(성공이든 실패든) 호출 1번과 쓴 토큰을 더한다."""
        key = (run_id, step)
        self._calls[key] = self._calls.get(key, 0) + 1
        self._tokens[key] = self._tokens.get(key, 0) + input_tokens


DEFAULT_BUDGET = CallBudget()


@dataclass(frozen=True)
class CallRecord:
    run_id: str
    step: str
    model: str
    input_tokens: int
    output_tokens: int
    cost: float | None
    elapsed_ms: int
    from_cache: bool
    attempt: int
    # ok / cache_hit / transport_error / limit_exceeded / invalid_output
    outcome: str


class CallRecorder(Protocol):
    def record(
        self,
        run_id: str,
        step: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: float | None,
        elapsed_ms: int,
        from_cache: bool,
        attempt: int,
        outcome: str,
    ) -> None: ...


class MemoryRecorder:
    """메모리에 쌓는 기록기 (DB agent_steps 구현은 #55 뒤)."""

    def __init__(self) -> None:
        self.records: list[CallRecord] = []

    def record(self, *args, **kwargs) -> None:
        self.records.append(CallRecord(*args, **kwargs))
