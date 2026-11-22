"""F3·F4 공통: 묶음(판단 단위) 하나의 모델 호출 실패를 그 묶음만 보류로 바꾸는 도구.

#166 (가): 예상 못 한 오류만 실행 failed. 묶음 하나의 호출 실패는 그 묶음만 보류
(확인되지 않음 + 이유)로 남기고 나머지는 끝까지 한다 (PRD F5 3번).
잡는 예외는 BUNDLE_ERRORS 세 가지뿐이다. `TypeError` 같은 프로그래밍 오류와 설정·입력 오류는
잡지 않는다. 호출 상한(ModelCallLimitExceeded)은 실패가 아니다: limit_reached로 보류하고 끝낸다
(ADR 0003). 단계 전체가 못 돈 때(시도한 묶음이 모두 실패)는 마지막 원래 예외를 그대로 올린다.
"""

import logging

from patent_ai.core.llm.errors import ModelCallFailed, ModelCallLimitExceeded, ModelOutputInvalid
from patent_ai.core.schemas.case_materials import HeldTask
from patent_ai.core.schemas.common import Status, StatusValue, UnverifiedReason

logger = logging.getLogger(__name__)

# 묶음 하나가 모델을 못 불러 못 끝낸 경우 (출력 검사 재시도 뒤에도 실패 / 전송 오류 / 호출 상한)
BUNDLE_ERRORS = (ModelOutputInvalid, ModelCallFailed, ModelCallLimitExceeded)

# F3 보류 작업 이름 끝에 붙이는 말: 이 끝말로 확인되지 않음의 이유를 정한다
CALL_FAILED = "call_failed"
LIMIT_REACHED = "limit_reached"
# 근거 다시 찾기의 도구(검색)가 환경 때문에 실패함. 확인되지 않음 + not_extracted로 센다
# (held_error_status가 None을 돌려줘도 F3 보류 기본값이 같은 status다)
TOOL_FAILED = "tool_failed"


# 진보성에서 독립항(대표 청구항)에 차이점이 있어 종속항을 대비하지 않은 보류의 끝말.
# 기다리는 자료가 없는 정해진 건너뜀이라 F3 결과·F4 후보 status를 낮추지 않는다
# (확인 사항 글만 싣는다)
DEPENDENT_SKIPPED = "dependent"


def is_dependent_skip(task: str) -> bool:
    """종속항 건너뜀 보류인가 (F3 run_f3와 F4 f3_gaps가 같이 쓰는 판별 한 곳)."""
    return task.endswith(f":{DEPENDENT_SKIPPED}")


def is_limit(error: Exception) -> bool:
    return isinstance(error, ModelCallLimitExceeded)


def failed_status(error: Exception) -> Status:
    """호출 상한이면 limit_reached, 그 밖의 호출 실패는 not_extracted (확인되지 않음)."""
    reason = UnverifiedReason.LIMIT_REACHED if is_limit(error) else UnverifiedReason.NOT_EXTRACTED
    return Status(value=StatusValue.UNVERIFIED, reason=reason)


def why(error: Exception) -> str:
    """결과에 남길 이유 글. 원문 글자는 넣지 않는다 (예외 종류와 상한 숫자만)."""
    if is_limit(error):
        return f"호출 상한 {error.limit} {error.limit_value}에 닿아 이 묶음은 처리하지 못함"  # type: ignore[attr-defined]
    return f"모델 호출이 실패해 이 묶음은 처리하지 못함 ({type(error).__name__})"


def raise_if_all_failed(step: str, tried: int, errors: list[Exception]) -> None:
    """모델을 부른 모든 묶음이 호출 실패(상한 제외)면 마지막 원래 예외를 그대로 올린다.

    tried는 모델 호출까지 간 묶음 수다 (부르기 전에 보류로 끝난 묶음은 세지 않는다).

    errors에는 상한이 아닌 호출 실패만 담는다 (상한은 실패가 아니라 보류로 끝낸다).
    """
    if tried and len(errors) == tried:
        logger.warning("%s: 모델을 부른 묶음 %d개가 모두 실패해 단계 실패로 올림", step, tried)
        raise errors[-1]


def hold_for_error(task_prefix: str, unit_id: str, error: Exception) -> HeldTask:
    """F3: 묶음 하나의 호출 실패를 보류 작업으로 바꾼다 (이유는 글자와 작업 이름 끝말에)."""
    kind = LIMIT_REACHED if is_limit(error) else CALL_FAILED
    detail = why(error)
    logger.warning("%s %s: %s (이 묶음만 보류)", task_prefix, unit_id, detail)
    return HeldTask(task=f"{task_prefix}:{unit_id}:{kind}", waiting_for=f"원문 확인 필요: {detail}")


def held_error_status(task: str) -> Status | None:
    """보류 작업 이름이 호출 실패·상한 끝말이면 그 status, 아니면 None."""
    if task.endswith(f":{LIMIT_REACHED}"):
        return Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.LIMIT_REACHED)
    if task.endswith(f":{CALL_FAILED}"):
        return Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
    return None
