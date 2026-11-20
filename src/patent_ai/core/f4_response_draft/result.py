"""F4 한 번 실행의 결과를 한데 담는 모델 (도구 출력).

저장하는 결과 스키마가 아니다: 저장은 안의 directions·drafts를 하나씩 한다.
결과 스키마(core/schemas)로 올릴 때 이름·칸을 그대로 옮긴다.
"""

from pydantic import BaseModel, ConfigDict, Field

from patent_ai.core.schemas.common import Flag, Status
from patent_ai.core.schemas.direction import DirectionCandidates
from patent_ai.core.schemas.drafts import Drafts


class F4Output(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    oa_id: str
    directions: list[DirectionCandidates]  # 판단 단위마다 하나 (order 순)
    drafts: Drafts | None  # OA 하나에 하나. 모든 묶음이 보류면 null
    held_units: list[str]  # 초안을 보류한 묶음 (사람이 방향을 고르거나 자료를 채우면 다시 만든다)
    unsupported_rejections: list[int]  # AI가 다루지 않은 거절이유 번호 (직접 대응 필요)
    uncovered: list[tuple[int, int]]  # 판단 단위가 덮지 않은 (거절이유 번호, 청구항 번호)
    # 최후거절이유통지 보정 제한을 보정 프롬프트에 넣었나 (스위치 켬 + 통지 종류 final일 때만 true).
    # 제한을 지켰다는 판정이 아니다: 넣었다는 사실만 적는다
    amendment_limit_applied: bool = False
    status: Status  # 방향 후보·초안 status 중 가장 나쁜 값
    flags: list[Flag] = Field(default_factory=list)
