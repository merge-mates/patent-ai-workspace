"""F3 단계들이 같이 쓰는 틀: 모델 1회 -> 코드 검사 -> 떨어지면 검사 오류를 붙여 한 번만 더.

모델 호출은 core/llm의 call_model만 거친다 (캐시·호출 상한·기록). 여기서는 다시 부르는 순서만 둔다.
"""

import logging
from collections.abc import Callable

from pydantic import BaseModel

from patent_ai.core.llm.client import call_model
from patent_ai.core.llm.errors import ModelOutputInvalid
from patent_ai.core.llm.limits import RunContext
from patent_ai.core.schemas.common import Status, StatusValue, UnverifiedReason

logger = logging.getLogger(__name__)

RETRY_NOTE = (
    "\n앞 답이 검사에 떨어졌습니다. 아래 오류를 고쳐 같은 형식으로 다시 답하세요.\n"
    "검사 오류:\n{error}\n"
)
MAX_ERROR_CHARS = 2000  # 오류 문구가 길면 앞부분만 (프롬프트가 불어나지 않게)


def call_checked[A: BaseModel, R](
    step: str,
    variables: dict[str, str],
    schema: type[A],
    check: Callable[[A], tuple[R, list[str]]],
    *,
    ctx: RunContext,
    who: str,
) -> R:
    """모델을 부르고 check로 검사한다. 떨어지면 검사 오류를 프롬프트에 붙여 한 번만 더 부른다.

    variables에는 빈 `retry_note` 칸이 있어야 한다 (프롬프트의 $retry_note 자리).
    check(모델 답) -> (결과, 검사 오류 글 목록). 오류가 비면 통과다.
    두 번째 답만 쓴다 (첫 답과 섞지 않는다). 두 번째 답에도 오류가 남으면 그 결과를 그대로
    돌려준다: 틀린 것을 버리거나 "확인되지 않음"으로 남기는 일은 부르는 쪽이 한다.
    두 번째 답도 형식(JSON·스키마)이 틀리면 ModelOutputInvalid를 그대로 던진다
    (실패를 성공으로 숨기지 않는다).
    who: 경고 로그에 쓸 이름 (예: "compare 청구항 3"). 원문 글자는 넣지 않는다.
    """
    try:
        first = call_model(step, variables, schema, ctx=ctx, attempt=1)
        result, errors = check(first.parsed)
        if not errors:
            return result
        error = "\n".join(errors)
    except ModelOutputInvalid as e:
        error = str(e)
    logger.warning("%s: 답이 검사에 떨어져 검사 오류를 붙여 한 번 더 부름", who)
    again = {**variables, "retry_note": RETRY_NOTE.format(error=error[:MAX_ERROR_CHARS])}
    second = call_model(step, again, schema, ctx=ctx, attempt=2)
    result, errors = check(second.parsed)
    if errors:
        logger.warning("%s: 다시 불러도 검사 오류 %d건", who, len(errors))
    return result


# ---- status 만들기 (세 단계가 같은 꼴로 쓴다) ----
def confirmed(checked: str) -> Status:
    """확인됨. checked에는 무엇을 확인했는지 적는다."""
    return Status(value=StatusValue.CONFIRMED, checked=checked)


def unverified(reason: UnverifiedReason) -> Status:
    """확인되지 않음 + 이유."""
    return Status(value=StatusValue.UNVERIFIED, reason=reason)
