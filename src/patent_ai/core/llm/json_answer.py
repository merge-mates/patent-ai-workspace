"""모델 답 글자에서 JSON을 읽는다.

모델은 JSON만 쓰라고 해도 코드 블록으로 감싸거나 끝에 괄호를 더 붙이는 일이 있다.
내용이 빠지지 않는 경우만 그 글자를 벗기고, 그 밖에는 JSONDecodeError를 그대로 낸다.
"""

import json
import logging
import re

logger = logging.getLogger(__name__)

# 맨 앞 코드 블록 표시 (```json 또는 ```)
_FENCE_OPEN = re.compile(r"\s*```(?:json)?\s*")
# 버려도 되는 꼬리: 공백·닫는 괄호·쉼표·코드 블록 표시·값이 null인 키뿐.
# 값이 든 꼬리는 JSON이 일찍 닫혀 밀려난 내용일 수 있어 버리지 않는다.
_EMPTY_TAIL = re.compile(r'(?:[\s\]},]|```|"[^"\\]*"\s*:\s*null)*')


def parse_answer(text: str, *, truncated: bool):
    """답을 JSON으로 읽는다. 잘린 답(truncated)은 벗기지 않는다."""
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        value = None if truncated else _strip_and_parse(text)
        if value is None:
            raise e
        return value


def _strip_and_parse(text: str) -> dict | None:
    """겉 글자를 벗겨 읽은 객체. 못 읽거나 내용이 빠질 수 있으면 None."""
    opened = _FENCE_OPEN.match(text)
    body = (text[opened.end() :] if opened else text).lstrip()
    if not body.startswith("{"):
        return None
    try:
        value, end = json.JSONDecoder().raw_decode(body)
    except json.JSONDecodeError:
        return None
    if _EMPTY_TAIL.fullmatch(body[end:]) is None:
        return None
    # 답 글자는 남기지 않고 모양만 남긴다
    logger.warning(
        "모델 답: JSON 밖 글자를 벗기고 읽음 (코드 블록=%s, 꼬리 %d자)",
        opened is not None,
        len(body) - end,
    )
    return value
