"""F4 한 번 실행의 결과를 한데 담는 모델 (도구 출력).

결과 스키마(core/schemas)가 아니라 도구 출력이다. 서버는 이 객체를 통째로 `step_results`(kind f4)에
저장하고, 결과 API가 안의 directions·drafts를 꺼내 준다 (#191, docs/data-model.md 5절).
결과 스키마로 올릴 때 이름·칸을 그대로 옮긴다.
"""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from patent_ai.core.f4_response_draft.plan_check import PlanIssue
from patent_ai.core.schemas.common import Flag, Status
from patent_ai.core.schemas.direction import DirectionCandidates
from patent_ai.core.schemas.drafts import Drafts
from patent_ai.core.schemas.judgment_unit import JudgmentUnit


class AmendmentOverlap(BaseModel):
    """같은 청구항을 두 묶음이 다 고쳐서, 앞선 묶음 초안만 싣고 뒤 묶음 초안은 싣지 않은 기록."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: int  # 겹친 청구항 번호
    kept_unit: str  # 초안을 실은 묶음 (order가 앞선 쪽)
    dropped_unit: str  # 초안을 싣지 않은 묶음 (사람이 직접 합쳐야 함)


class F4Output(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    oa_id: str
    units: list[JudgmentUnit]  # 이 실행에 넣은 판단 단위 (채점·다시 내기가 결과 하나로 되게)
    directions: list[DirectionCandidates]  # 판단 단위마다 하나 (order 순)
    drafts: Drafts | None  # OA 하나에 하나. 모든 묶음이 보류면 null
    held_units: list[str]  # 초안을 보류한 묶음 (사람이 방향을 고르거나 자료를 채우면 다시 만든다)
    unsupported_rejections: list[int]  # AI가 다루지 않은 거절이유 번호 (직접 대응 필요)
    uncovered: list[tuple[int, int]]  # 판단 단위가 덮지 않은 (거절이유 번호, 청구항 번호)
    # 대상 청구항을 못 읽어 누락 검사를 못 한 거절이유 번호 (uncovered가 비어도 누락 없음이 아님)
    coverage_unchecked: list[int] = Field(default_factory=list)
    # 같은 청구항을 여러 묶음이 고쳐 뒤 묶음 초안을 싣지 않은 기록 (Drafts.flags는 늘 붙어 있어
    # 구분이 안 되므로 따로 남긴다). 의견서 쪽 겹침은 이 단계에서 다루지 않는다
    amendment_overlaps: list[AmendmentOverlap] = Field(default_factory=list)
    # 묶음(unit_id)마다 보정 범위로 넓힌 항 = 거절 대상이 아닌데 보정 후보에 쓸 수 있는 항
    # (ADR 0005).
    # 화면·채점이 "AI가 거절 대상 밖 항을 제안했다"를 가르게 남긴다. 결과 스키마에는 칸이 없다
    amendment_scopes: dict[str, list[int]] = Field(default_factory=dict)
    # 최후거절이유통지 보정 제한을 보정 프롬프트에 넣었나 (스위치 켬 + 통지 종류 final일 때만 true).
    # 제한을 지켰다는 판정이 아니다: 넣었다는 사실만 적는다
    amendment_limit_applied: bool = False
    # 화면·API가 결과와 함께 보일 알림 문구 (결과 스키마에 칸이 없어 여기 싣는다)
    rank_notice: str  # 순위는 검토 순서 제안이고 등록 가능성 보증이 아님
    legality_notice: str  # 보정 초안은 검토용이고 적법성은 판단하지 않음
    # 방향 후보·초안 status 중 가장 나쁜 값. 값은 원문 확인 여부만 뜻한다:
    # 보류·누락처럼 사람이 봐야 할 것은 flags·held_units·uncovered로 본다
    status: Status
    flags: list[Flag] = Field(default_factory=list)
    # 이 결과를 만든 확인 기준일 (F4Input.checked_on). 초안만 다시 만드는 실행이 이어 쓴다 (#293).
    # 이 칸이 생기기 전에 저장한 결과는 None
    checked_on: date | None = None
    # 사건 단위 보정안(case_amendment)을 쓴 실행:
    # 1번 안의 전략 글, 다른 안의 전략 글, 코드 검사 표시.
    # 보정 청구항 자체는 drafts.claims에 실린다. 쓰지 않은 실행은 None·빈 목록
    amendment_strategy: str | None = None
    amendment_alternatives: list[str] = Field(default_factory=list)
    amendment_checks: list[PlanIssue] = Field(default_factory=list)
    # 의견서만 실행(amendment_enabled false): 고른 방향의 보정 유무가 바깥 보정 결과와 어긋난 묶음.
    # 의견서는 바깥 보정 결과를 따르고, 방향 품질은 따로 본다 (11/26 D2-1)
    direction_amendment_mismatch: list[str] = Field(default_factory=list)
