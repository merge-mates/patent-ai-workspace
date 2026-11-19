"""채점기 오류. 메시지에는 row_id와 건수만 쓴다 (질의·정답 원문 글자 금지)."""


class RetrievalEvalError(Exception):
    """채점을 시작할 수 없거나 계속할 수 없을 때. CLI 종료 코드 1."""
