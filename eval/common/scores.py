"""scores.json 쓰기. 필수 칸은 experiments/_template/scores.schema.json 한 곳에서 읽는다."""

import json
from pathlib import Path

from eval.common.errors import EvalError
from eval.common.paths import REPO_ROOT

SCHEMA_PATH = REPO_ROOT / "experiments" / "_template" / "scores.schema.json"


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v: object) -> bool:
    return (isinstance(v, int | float)) and not isinstance(v, bool)


def check_scores(scores: dict) -> None:
    """스키마의 필수 칸과 꼴을 본다. 틀리면 칸 이름만 담은 EvalError."""
    required = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["required"]
    missing = [k for k in required if k not in scores]
    if missing:
        raise EvalError(f"scores.json 필수 칸이 빠졌다: {', '.join(missing)}")
    if not _is_int(scores["goldset_version"]):
        raise EvalError("scores.json goldset_version이 정수가 아니다")
    if not _is_int(scores["n"]):
        raise EvalError("scores.json n이 정수가 아니다")
    # 채점한 문항이 0개인데 성공으로 끝나지 않는다 (조용한 실패 금지)
    if scores["n"] <= 0:
        raise EvalError("scores.json n이 0이다 (채점한 문항 없음)")
    if not isinstance(scores["metrics"], dict) or not all(
        _is_number(v) for v in scores["metrics"].values()
    ):
        raise EvalError("scores.json metrics 값은 숫자여야 한다 (못 잰 지표는 키를 뺀다)")
    if not isinstance(scores["failures"], dict) or not all(
        _is_int(v) for v in scores["failures"].values()
    ):
        raise EvalError("scores.json failures 값은 정수(건수)여야 한다")
    if not isinstance(scores["cost"], dict):
        raise EvalError("scores.json cost가 객체가 아니다")


def write_scores(scores_dir: str | Path, scores: dict) -> Path:
    """검사를 통과하면 <scores_dir>/scores.json을 쓰고 그 경로를 돌려준다."""
    check_scores(scores)  # 틀리면 파일을 쓰기 전에 멈춘다
    out_dir = Path(scores_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "scores.json"
    out.write_text(json.dumps(scores, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out
