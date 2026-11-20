"""F4 예측 읽기: F4 실행 결과에서 채점에 쓰는 것만 꺼낸다.

예측 폴더 (git 밖):
- <출원번호>_<발송번호>.json: run_f4 결과(F4Output dump, `directions` 칸을 씀)
  또는 DirectionCandidates 목록
- <출원번호>_<발송번호>.units.json: 그 실행에 넣은 판단 단위(JudgmentUnit) 목록.
  DirectionCandidates에는 묶음의 거절이유 번호·청구항 목록이 없어 이 파일로 줄에 잇는다.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from eval.common.errors import EvalError
from patent_ai.core.schemas.direction import DirectionCandidates
from patent_ai.core.schemas.judgment_unit import JudgmentUnit

logger = logging.getLogger(__name__)

UNITS_SUFFIX = ".units.json"
_DIRECTIONS = TypeAdapter(list[DirectionCandidates])
_UNITS = TypeAdapter(list[JudgmentUnit])


@dataclass(frozen=True)
class F4Pred:
    units: list[JudgmentUnit]
    directions: dict[str, DirectionCandidates]  # unit_id -> 그 묶음의 방향 후보 결과


def _read_json(path: Path, where: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise EvalError(f"{where}: JSON 문법이 틀리다") from None


def load_predictions(folder: Path) -> dict[str, F4Pred]:
    """예측 폴더를 읽는다. 키는 파일 이름(확장자 뺀 것) = OA 키. 틀린 파일은 순번만 말한다."""
    if not folder.is_dir():
        raise EvalError("F4 예측 폴더가 없다")
    files = sorted(f for f in folder.glob("*.json") if not f.name.endswith(UNITS_SUFFIX))
    preds: dict[str, F4Pred] = {}
    for i, f in enumerate(files, start=1):
        where = f"예측 파일 {i}번째"  # 파일 이름(출원번호)과 원문 글자는 메시지에 넣지 않는다
        data = _read_json(f, where)
        if isinstance(data, dict):
            data = data.get("directions")  # F4Output dump
        try:
            directions = _DIRECTIONS.validate_python(data)
        except ValidationError:
            raise EvalError(
                f"{where}: DirectionCandidates 목록(또는 F4Output) 모양이 아니다"
            ) from None
        units_file = f.with_name(f.stem + UNITS_SUFFIX)
        if not units_file.is_file():
            raise EvalError(f"{where}: 판단 단위 파일(<같은 이름>{UNITS_SUFFIX})이 없다")
        try:
            units = _UNITS.validate_python(_read_json(units_file, where + " 판단 단위"))
        except ValidationError:
            raise EvalError(f"{where}: 판단 단위 파일이 JudgmentUnit 목록 모양이 아니다") from None
        known = {u.unit_id for u in units}
        dropped = [d for d in directions if d.unit_id not in known]
        if dropped:
            # 거절이유·청구항에 이을 수 없어 채점에 못 쓴다 (그 줄은 누락으로 세어진다)
            logger.warning(
                "%s: 판단 단위 파일에 없는 묶음의 방향 결과 %d건 (채점에 쓰지 않음)",
                where,
                len(dropped),
            )
        preds[f.stem] = F4Pred(
            units=units, directions={d.unit_id: d for d in directions if d.unit_id in known}
        )
    return preds
