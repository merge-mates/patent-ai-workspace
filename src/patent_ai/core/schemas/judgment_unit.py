"""JudgmentUnit(②): 판단 단위. 모양의 기준은 docs/data-model.md 3절 ② 줄.

unit_id는 내용으로 정한다: `<OA ID>:<조문>:c<대표 청구항>` (하위 단위는 `/<글자>`를 덧붙임).
같은 묶음은 다시 돌려도 같은 ID라 사람이 고른 선택이 이어진다.
"""

import re
from enum import StrEnum

from pydantic import model_validator

from patent_ai.core.schemas.common import ResultBase
from patent_ai.core.schemas.oa_result import RejectionKind

# 예: oa_1:29-2:c1, oa_1:29-2:c1/a, oa_1:29-2:c1/a/b
# 조문은 `29-2`처럼 하나, 호가 여럿이면 `29-1-1|29-1-2`처럼 `|`로 잇는다
_ARTICLE = r"[0-9]+(?:-[0-9]+)*"
UNIT_ID_FORM = re.compile(rf"[^:]+:{_ARTICLE}(?:\|{_ARTICLE})*:c(?P<claim>[1-9]\d*)(?:/[a-z])*")


class UnitKind(StrEnum):
    INDEPENDENT_GROUP = "independent_group"  # 독립항 묶음 (진보성·신규성)
    SINGLE_CLAIM = "single_claim"  # 청구항 하나 (명확성)


class JudgmentUnit(ResultBase):
    unit_id: str
    rejection: int  # OAResult rejections[].no
    rejection_kind: RejectionKind
    unit_kind: UnitKind
    representative_claim: int
    claims: list[int]  # 대표 독립항 + 묶음 안 종속항
    read_with: list[int] = []  # 명확성만: 함께 읽을 청구항
    order: int  # 독립항 먼저
    parent_unit_id: str | None = None  # 무너진 묶음을 나눌 때 원래 단위

    @model_validator(mode="after")
    def _검사(self) -> JudgmentUnit:
        # 조문을 모르는 거절이유는 판단 단위를 만들지 않는다
        if self.rejection_kind == RejectionKind.OTHER:
            raise ValueError("rejection_kind가 other면 판단 단위를 만들지 않음")
        # 명확성은 청구항 하나, 진보성·신규성은 독립항 묶음
        is_clarity = self.rejection_kind == RejectionKind.CLARITY
        if is_clarity != (self.unit_kind == UnitKind.SINGLE_CLAIM):
            raise ValueError("clarity는 single_claim, novelty·inventive_step은 independent_group")
        if not self.claims:
            raise ValueError("claims가 비어 있음")
        if len(set(self.claims)) != len(self.claims):
            raise ValueError("claims에 중복이 있음")
        if self.representative_claim not in self.claims:
            raise ValueError("claims에 representative_claim이 없음")
        if self.read_with and not is_clarity:
            raise ValueError("read_with는 clarity일 때만")
        if is_clarity:
            # 명확성은 청구항 하나만 담고, 함께 읽을 청구항에 자기 자신은 넣지 않는다
            if self.claims != [self.representative_claim]:
                raise ValueError("single_claim의 claims는 [representative_claim]")
            if self.representative_claim in self.read_with:
                raise ValueError("read_with에 대표 청구항이 들어 있음")
        # unit_id 꼴과 대표 청구항·부모 단위가 맞아야 한다
        m = UNIT_ID_FORM.fullmatch(self.unit_id)
        if m is None:
            raise ValueError(f"unit_id 꼴이 아님: {self.unit_id}")
        if int(m["claim"]) != self.representative_claim:
            raise ValueError("unit_id의 c번호가 representative_claim과 다름")
        if self.parent_unit_id is not None and not self.unit_id.startswith(
            self.parent_unit_id + "/"
        ):
            raise ValueError("unit_id가 parent_unit_id + '/'로 시작하지 않음")
        return self
