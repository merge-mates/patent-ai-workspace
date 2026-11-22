"""모델을 부르는 impl(whole_doc_llm)의 비용 칸·실패 칸·예산 검사 (이슈 #248).

호출 기록(CallRecord)은 core/llm이 쌓는다. 여기서는 그 합만 낸다
(core를 import하지 않고 모양만 읽는다).
기록 하나 = API 요청 하나 (limit_exceeded 기록은 요청을 보내기 전에 막힌 것이라 요청이 아니다).
"""

import logging
from collections.abc import Sequence

from eval.retrieval.errors import RetrievalEvalError

logger = logging.getLogger(__name__)

# 출력 검사에 떨어진 호출 (core/llm/client.py의 outcome 이름)
INVALID_OUTCOMES = ("invalid_output", "output_truncated")


def _requests(records: Sequence) -> list:
    """실제로 API를 부른 기록. 캐시 적중과 상한에 막힌 기록은 뺀다."""
    return [r for r in records if not r.from_cache and r.outcome != "limit_exceeded"]


def _sum_or_none(values: list) -> int | float | None:
    # 하나라도 모르면(None) 합도 모른다: 0으로 메우지 않는다
    return None if any(v is None for v in values) else sum(values)


def spent(records: Sequence) -> tuple[int, int | float | None]:
    """(실제 호출 수, 쓴 USD). USD는 모르는 기록이 있으면 None."""
    reqs = _requests(records)
    return len(reqs), _sum_or_none([r.cost for r in reqs])


def cost_fields(records: Sequence, seconds: float) -> dict:
    """scores.json cost 칸. 토큰·USD는 돈이 나간 호출만 합한다 (캐시 적중은 청구 없음)."""
    reqs = _requests(records)
    return {
        "usd": _sum_or_none([r.cost for r in reqs]),
        "input_tokens": _sum_or_none([r.input_tokens for r in reqs]),
        "output_tokens": _sum_or_none([r.output_tokens for r in reqs]),
        "external_calls": len(reqs),
        "model_calls": len(records),  # 캐시 적중 포함 전체 기록 수
        "cache_hits": sum(1 for r in records if r.from_cache),
        "seconds": seconds,
    }


def invalid_attempts(records: Sequence) -> int:
    """출력 검사에 떨어진 시도 수 (다시 부른 시도 포함)."""
    return sum(1 for r in records if r.outcome in INVALID_OUTCOMES)


def check_budget(records: Sequence, max_usd: float | None, max_external_calls: int | None) -> None:
    """줄을 검색하기 전에 부른다. 지금까지 쓴 양이 상한 이상이면 멈춘다.

    멈추면 scores.json을 쓰지 않는다 (반쯤 채점한 점수를 남기지 않게).
    """
    calls, usd = spent(records)
    if max_external_calls is not None and calls >= max_external_calls:
        raise RetrievalEvalError(
            f"budget.max_external_calls 상한에 닿아 멈춤 (쓴 호출 {calls}/{max_external_calls})"
        )
    if max_usd is not None:
        if usd is None:
            # 비용을 모르는 호출이 있으면 USD 상한은 지킬 수 없다: 소리 내서 알린다
            logger.warning("호출 비용을 모르는 기록이 있어 max_usd를 확인할 수 없음")
        elif usd >= max_usd:
            raise RetrievalEvalError(
                f"budget.max_usd 상한에 닿아 멈춤 (쓴 ${usd:.6f} / ${max_usd})"
            )
