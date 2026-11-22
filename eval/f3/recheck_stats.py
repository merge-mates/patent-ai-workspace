"""다시 찾기(recheck) 도구 쓰임 통계: 예측 폴더의 F3Result.recheck_log만 본다.

구성요소당 도구 호출 수(평균·최대), 차례 수, 끝 상태별 수, give_up 비율.
실험 실행 스크립트가 scores 옆에 낸다. 건수와 비율만 있고 번호·원문 글자는 없다.
"""

from pathlib import Path

from pydantic import ValidationError

from eval.common.errors import EvalError
from eval.f3.pred import F3Pred

OUTCOMES = ("submitted", "gave_up", "limit_reached", "model_call_failed", "tool_failed")


def recheck_stats(folder: Path) -> dict:
    """<폴더>/*.f3.json의 recheck_log를 합쳐 센다. 기록이 없으면 components 0, 평균은 None."""
    if not folder.is_dir():
        raise EvalError("F3 예측 폴더가 없다")
    logs = []
    for i, f in enumerate(sorted(folder.glob("*.f3.json")), start=1):
        try:
            logs += F3Pred.model_validate_json(f.read_text(encoding="utf-8")).recheck_log
        except ValidationError:
            raise EvalError(f"예측 파일 {i}번째: F3Result 모양이 아니다") from None
    n = len(logs)
    outcomes = {name: sum(1 for r in logs if r.outcome == name) for name in OUTCOMES}
    calls = [r.tool_calls for r in logs]
    turns = [r.turns for r in logs]
    return {
        "components": n,
        "tool_calls_mean": sum(calls) / n if n else None,
        "tool_calls_max": max(calls) if n else None,
        "turns_mean": sum(turns) / n if n else None,
        "turns_max": max(turns) if n else None,
        "outcomes": outcomes,
        "give_up_rate": outcomes["gave_up"] / n if n else None,
    }
