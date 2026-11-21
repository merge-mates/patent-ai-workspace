"""F4 대응 방향 정답 읽기와 형식 검사. 모양의 기준은 docs/evaluation/f4-direction-gold.md 4절(초안).

OA 한 통에 파일 하나 (<세트>/f4/<출원번호>_<발송번호>.json). 한 줄 = OA 시점 청구항 × 거절이유.
오류 메시지에는 파일 순번·칸 이름만 쓴다 (파일 이름에 출원번호가 있어 찍지 않는다).
"""

import json
import logging
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from eval.common.errors import EvalError

logger = logging.getLogger(__name__)

Direction = Literal["argue_only", "amend_and_argue", "amend_only"]
# ③ 보정 종류. 문서 예시는 그대로를 `none`으로 적고, DirectionCandidates 코드는 `unchanged`다.
# 코드 이름이 F4 설계 때 확정되기 전이라 둘 다 받는다 (③은 아직 채점하지 않음)
AmendKind = Literal["none", "unchanged", "limit", "add", "delete", "correct_error", "clarify"]


class NoGold(EvalError):
    """정답 폴더가 없거나 비었다. 채점 실패가 아니라 "정답 없음"으로 끝낸다 (점수를 쓰지 않음)."""


class GoldSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opinion: str  # 의견서 접수번호
    amendment: str | None  # 보정서 접수번호. 보정서가 없으면 null


class GoldReviewed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by: str | None
    date: str | None


class GoldClaimRow(BaseModel):
    """정답 한 줄 = OA 시점 청구항 × 거절이유."""

    model_config = ConfigDict(extra="forbid")

    claim: int = Field(ge=1)
    rejection: int = Field(ge=1)  # F1 정답 rejections[].no (OA 순번)
    handled: bool  # ① 다뤘나
    direction: Direction | None  # ② 거친 방향. 안 다룸이면 null
    inherited: bool  # 자기가 인용하는 청구항의 ②를 물려받은 줄 (3절 1·14번)
    amend_kinds: list[AmendKind]  # ③ 보정 종류 (여럿 가능)
    added_from: list[str]  # ③ 더한 구성의 출처
    # ③ 삭제 줄: 지운 구성을 옮겨 받은 청구항 (4절, 채점에는 안 씀)
    merged_into: list[Annotated[int, Field(strict=True, ge=1)]] = []
    argued: bool  # ④ 의견서가 따로 논증한 줄인가

    @model_validator(mode="after")
    def _다룸과_방향(self) -> GoldClaimRow:
        # 3절 13번: 안 다룸 줄의 ②는 없음. 다룬 줄은 ②가 있어야 채점할 수 있다
        if self.handled != (self.direction is not None):
            raise ValueError("handled가 true일 때만, 그리고 그때는 꼭 direction을 채운다")
        if not self.amend_kinds:
            raise ValueError("amend_kinds가 비어 있음 (그대로면 none)")
        if self.merged_into and "delete" not in self.amend_kinds:
            raise ValueError("merged_into는 amend_kinds에 delete가 있는 줄에만 둔다")
        return self


class F4Gold(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gold_version: int
    source: GoldSource
    reviewed: GoldReviewed
    new_claims: int = Field(ge=0)  # 신설 청구항 수 (청구항 줄로 두지 않음)
    claim_rows: list[GoldClaimRow]

    @model_validator(mode="after")
    def _줄은_한_번씩(self) -> F4Gold:
        keys = [(r.claim, r.rejection) for r in self.claim_rows]
        if len(set(keys)) != len(keys):
            raise ValueError("claim_rows에 같은 (청구항, 거절이유) 줄이 두 번 있음")
        return self


def _lines(e: ValidationError) -> list[str]:
    """검사 오류를 칸 경로와 이유만으로 (입력 값 글자는 싣지 않는다)."""
    return [f"{'.'.join(str(x) for x in err['loc'])}: {err['type']}" for err in e.errors()]


def load_f4_gold(folder: str | Path, expected_version: int) -> dict[str, F4Gold]:
    """정답 폴더의 *.json을 이름 순서로 읽는다. 키는 파일 이름(확장자 뺀 것) = OA 키.

    폴더가 없거나 파일이 0개면 NoGold. 하나라도 모양이 틀리면 EvalError로 멈춘다.
    """
    d = Path(folder)
    if not d.is_dir():
        raise NoGold("F4 정답 폴더가 없다")
    files = sorted(d.glob("*.json"))
    if not files:
        raise NoGold("F4 정답 파일이 0개다")

    golds: dict[str, F4Gold] = {}
    for i, f in enumerate(files, start=1):
        where = f"정답 파일 {i}번째"
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise EvalError(f"{where}: JSON 문법이 틀리다") from None
        try:
            g = F4Gold.model_validate(data)
        except ValidationError as e:
            raise EvalError(f"{where}: " + "; ".join(_lines(e)[:5])) from None
        if g.gold_version != expected_version:
            raise EvalError(
                f"{where}: gold_version이 다르다: 파일 {g.gold_version}, VERSION {expected_version}"
            )
        if not g.claim_rows:
            logger.warning("%s: 청구항 줄이 0개다", where)
        golds[f.stem] = g
    return golds
