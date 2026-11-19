"""채점기 오류. 메시지에는 row_id와 건수만 쓴다 (질의·정답 원문 글자 금지).

공통 오류(eval/common/errors.py)와 같은 것이다. 검색 쪽 이름을 그대로 쓰는 코드·테스트를 위해 둔다.
"""

from eval.common.errors import EvalError

RetrievalEvalError = EvalError
