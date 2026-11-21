"""F4 입력 모델(앞 단계 결과 + 청구항·명세서 글자)과 F2가 없을 때 쓰는 빈 법률 근거 묶음.

글자를 입력 모델에 직접 싣는다 (도구 입력이 JSON으로 왕복하고, 모델 호출 캐시 키도 JSON이어야 해서).
"""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from patent_ai.core.schemas.common import Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.comparison import ClarityReview, ComparisonTable
from patent_ai.core.schemas.document import PageText
from patent_ai.core.schemas.judgment_unit import JudgmentUnit
from patent_ai.core.schemas.legal_evidence import (
    AsOfSource,
    LegalEvidenceBundle,
    LegalQuestion,
    LegalSourceKind,
    QuestionSource,
)
from patent_ai.core.schemas.oa_result import OAResult


class ClaimText(BaseModel):
    """OA 당시 청구항 하나의 글자."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: int = Field(ge=1)
    text: str
    document_id: str  # 이 글자를 읽은 문서 (OA 당시 청구항이 담긴 판)


class F4Input(BaseModel):
    """F4 한 번 실행의 입력. OA 하나와 그 판단 단위들, 앞 단계(F3·F2) 결과, 글자."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    oa: OAResult
    units: list[JudgmentUnit]
    tables: list[ComparisonTable] = Field(default_factory=list)  # F3 진보성·신규성 대비표
    clarity: list[ClarityReview] = Field(default_factory=list)  # F3 명확성 검토
    legal: list[LegalEvidenceBundle] = Field(default_factory=list)  # F2 결과. 비면 빈 묶음을 씀
    claims_text: list[ClaimText]
    spec: PageText | None = None  # 최초 명세서 쪽 글자. 없으면 보정 근거 위치는 보류
    checked_on: date  # 확인 기준일 (실행한 날. 코드가 오늘 날짜를 몰래 읽지 않게 입력으로 받음)


def empty_legal_bundle(oa_id: str, unit: JudgmentUnit, checked_on: date) -> LegalEvidenceBundle:
    """F2를 아직 안 돌린 묶음의 빈 법률 근거 묶음.

    status는 확인되지 않음(not_extracted)이다. "조회 범위 내 없음"은 쓰지 않는다:
    찾아보지 않았는데 그렇게 적으면 못 찾음을 없음으로 쓰는 셈이 된다.
    """
    return LegalEvidenceBundle(
        bundle_id=f"lb:{unit.unit_id}",
        unit_id=unit.unit_id,
        oa_id=oa_id,
        rejection=unit.rejection,
        question=LegalQuestion(
            text=f"거절이유 {unit.rejection} 법률 근거 (F2 미연결)",
            source=QuestionSource.OA_REJECTION,
            as_of=None,
            as_of_source=AsOfSource.NONE,
            source_kinds=[LegalSourceKind.STATUTE, LegalSourceKind.GUIDELINE],
        ),
        checked_on=checked_on,
        claims=[],
        status=Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED),
    )


def legal_bundle_for(inp: F4Input, unit: JudgmentUnit) -> LegalEvidenceBundle:
    """이 묶음의 법률 근거 묶음. 입력에 있으면 그것, 없으면 빈 묶음(확인되지 않음)."""
    for bundle in inp.legal:
        if bundle.unit_id == unit.unit_id:
            return bundle
    return empty_legal_bundle(inp.oa.oa_id, unit, inp.checked_on)
