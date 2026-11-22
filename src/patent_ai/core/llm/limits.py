"""호출 상한 세기와 호출 기록. 상태는 객체(CallBudget·MemoryRecorder)에 두고 call_model에 넘긴다."""

import logging
from dataclasses import dataclass
from typing import Protocol

from patent_ai.core.llm.cache import Cache
from patent_ai.core.llm.errors import ModelCallLimitExceeded
from patent_ai.core.llm.transport import Transport

logger = logging.getLogger(__name__)


class CallBudget:
    """실행(run_id)·단계(step)마다 쓴 호출 수와 입력 토큰 수를 센다.

    실행(run)마다 지휘가 새로 만들어 call_model에 넘긴다. 전역 객체는 없다.
    """

    def __init__(self) -> None:
        self._calls: dict[tuple[str, str], int] = {}
        self._tokens: dict[tuple[str, str], int] = {}
        self._warned: set[tuple[str, str]] = set()

    def check(
        self, run_id: str, step: str, max_calls: int | None, max_input_tokens: int | None
    ) -> None:
        """전송층을 부르기 직전에 부른다. 이미 상한만큼 썼으면 예외."""
        key = (run_id, step)
        # 상한 설정이 없으면 제한 없이 부르되, 실행·단계마다 경고는 한 번만
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


@dataclass(frozen=True)
class CallRecord:
    run_id: str
    step: str
    model: str
    # None = 확인되지 않음 (스트림이 끊겨 usage를 못 받음, #194). 0과 다르다: 0은 청구 없음을 앎
    input_tokens: int | None
    output_tokens: int | None
    cost: float | None
    elapsed_ms: int
    from_cache: bool
    attempt: int
    # ok / cache_hit / transport_error / limit_exceeded / invalid_output / output_truncated
    # 출력 검사에 떨어진 답은 둘로 나눈다: output_truncated = max_tokens에 닿아 잘림
    # (stop_reason = max_tokens), invalid_output = 그 밖 (끝까지 답했는데 모양이 틀림)
    outcome: str
    # 전송 시도 번호 (1부터, 재시도마다 +1). 캐시 적중은 0
    transport_try: int
    # 모델이 답을 끝낸 이유 (end_turn·max_tokens 등). 답을 못 받았거나 모르면 None
    stop_reason: str | None = None
    # 출력 검사에 떨어진 오류 종류 (#228). 답 원문 글자 없이 짧은 코드만 남긴다:
    # not_json / unknown_key / missing_key / bad_value. 스키마 칸을 알면 `종류:칸 경로`
    # (리스트 번호·모델이 쓴 키 이름은 뺌, 예: bad_value:rows.number). 여럿이면 쉼표로 잇는다.
    # 검사를 통과했거나 검사 전에 끝난 호출은 None
    invalid_kind: str | None = None


class CallRecorder(Protocol):
    def record(self, rec: CallRecord) -> None: ...


class MemoryRecorder:
    """메모리에 쌓는 기록기 (DB agent_steps 구현은 #55 뒤)."""

    def __init__(self) -> None:
        self.records: list[CallRecord] = []

    def record(self, rec: CallRecord) -> None:
        self.records.append(rec)


@dataclass
class RunContext:
    """실행(run) 하나의 모델 호출 맥락. 지휘가 실행마다 하나 만들어 도구에 넘긴다.

    같은 ctx로 부른 호출은 상한(budget)을 같이 쓰고 기록(recorder)이 한 곳에 쌓인다.
    transport가 None이면 진짜 전송층, cache가 None이면 진짜 전송층만 파일 캐시를 쓴다.
    """

    run_id: str
    budget: CallBudget
    recorder: CallRecorder
    transport: Transport | None = None
    cache: Cache | bool | None = None
