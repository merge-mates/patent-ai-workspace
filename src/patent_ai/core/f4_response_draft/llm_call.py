"""F4 단계 공용 모델 호출: 한 번 부르고, 출력 검사에 떨어지면 검사 오류를 붙여 한 번만 더 부른다.

F1 read_oa와 같은 길이다. 두 번째도 떨어지면 ModelOutputInvalid를 그대로 던진다
(실패를 빈 결과로 바꾸지 않는다. 지휘가 실행 failed로 남긴다).
"""

import logging

from pydantic import BaseModel

from patent_ai.core.llm.client import call_model
from patent_ai.core.llm.errors import ModelOutputInvalid
from patent_ai.core.llm.limits import RunContext

logger = logging.getLogger(__name__)

RETRY_NOTE = (
    "\n앞 답이 출력 형식 검사에 떨어졌습니다. 아래 오류를 고쳐 같은 형식으로 다시 답하세요.\n"
    "검사 오류:\n{error}\n"
)
MAX_ERROR_CHARS = 2000  # 오류 문구가 길면 앞부분만 (프롬프트가 불어나지 않게)


def call_with_one_retry[T: BaseModel](
    step: str, variables: dict[str, str], output_schema: type[T], ctx: RunContext
) -> T:
    """프롬프트에는 `$retry_note` 자리가 있어야 한다 (첫 호출은 빈 글자)."""
    try:
        first = call_model(step, {**variables, "retry_note": ""}, output_schema, ctx=ctx, attempt=1)
        return first.parsed  # type: ignore[return-value]
    except ModelOutputInvalid as e:
        error = str(e)[:MAX_ERROR_CHARS]
        logger.warning("%s: 모델 답이 검사에 떨어져 검사 오류를 붙여 한 번 더 부름", step)
    retry = {**variables, "retry_note": RETRY_NOTE.format(error=error)}
    second = call_model(step, retry, output_schema, ctx=ctx, attempt=2)
    return second.parsed  # type: ignore[return-value]
