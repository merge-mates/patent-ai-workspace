"""F3·F4 결과 엔드포인트 (이슈 #191 T3). 고르는 판단은 core/cases/result_views.py에 있다.

모양: `{oa_id, run_id, result, empty_reason}`. result에 결과 스키마 목록(초안은 하나)을 담는다.
보여 줄 실행이 없으면 404 result_not_ready, 그 실행에 결과가 없으면 200 + 빈 값 + empty_reason.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from patent_ai.api.deps import (
    CaseUnit,
    get_case_unit,
    get_oa_result_store,
    get_run_status_store,
    get_step_result_store,
)
from patent_ai.api.errors import AppError
from patent_ai.core.cases.result_views import ResultName, ResultView, result_view
from patent_ai.core.cases.results import OAResultStore
from patent_ai.core.cases.step_results import StepResultStore
from patent_ai.core.f4_response_draft.result import F4Output
from patent_ai.core.runs.store import RunStatusStore
from patent_ai.core.schemas.comparison import ClarityReview, ComparisonTable
from patent_ai.core.schemas.direction import DirectionCandidates
from patent_ai.core.schemas.drafts import Drafts
from patent_ai.core.schemas.judgment_unit import JudgmentUnit
from patent_ai.core.schemas.legal_evidence import LegalEvidenceBundle

router = APIRouter()


class _ListOut(BaseModel):
    oa_id: str
    run_id: str  # 이 결과를 만든 실행 (OA 정리와 같은 실행)
    empty_reason: str | None  # result가 비었을 때만 (넘김·보류·해당 없음)


class UnitsOut(_ListOut):
    result: list[JudgmentUnit]


class ComparisonsOut(_ListOut):
    result: list[ComparisonTable]


class ClarityReviewsOut(_ListOut):
    result: list[ClarityReview]


class LegalEvidenceOut(_ListOut):
    result: list[LegalEvidenceBundle]


class DirectionsOut(_ListOut):
    result: list[DirectionCandidates]
    rank_notice: str | None  # 순위는 검토 순서 제안이고 등록 가능성 보증이 아님


class DraftsOut(BaseModel):
    oa_id: str
    run_id: str
    result: Drafts | None  # 모든 묶음을 보류했거나 F4를 넘겼으면 null
    empty_reason: str | None
    held_units: list[str]  # 초안을 보류한 묶음
    legality_notice: str | None  # 보정 초안은 검토용이고 적법성은 판단하지 않음


Results = Annotated[OAResultStore, Depends(get_oa_result_store)]
Steps = Annotated[StepResultStore, Depends(get_step_result_store)]
Runs = Annotated[RunStatusStore, Depends(get_run_status_store)]
Unit = Annotated[CaseUnit, Depends(get_case_unit)]


def _view(oa_id: str, name: ResultName, unit, results, steps, runs) -> ResultView:
    if unit.store.get_oa(oa_id) is None:
        raise AppError(404, "oa_not_found", "OA를 찾을 수 없습니다")
    view = result_view(oa_id, name, oa_results=results, step_results=steps, runs=runs)
    if view is None:
        raise AppError(404, "result_not_ready", "결과가 아직 없습니다")
    return view


def _list(cls, oa_id: str, view: ResultView, **extra):
    return cls(
        oa_id=oa_id, run_id=view.run_id, result=view.value, empty_reason=view.empty_reason, **extra
    )


@router.get("/oas/{oa_id}/units", response_model=UnitsOut)
def get_units(oa_id: str, unit: Unit, results: Results, steps: Steps, runs: Runs) -> UnitsOut:
    return _list(UnitsOut, oa_id, _view(oa_id, "units", unit, results, steps, runs))


@router.get("/oas/{oa_id}/comparisons", response_model=ComparisonsOut)
def get_comparisons(
    oa_id: str, unit: Unit, results: Results, steps: Steps, runs: Runs
) -> ComparisonsOut:
    return _list(ComparisonsOut, oa_id, _view(oa_id, "comparisons", unit, results, steps, runs))


@router.get("/oas/{oa_id}/clarity-reviews", response_model=ClarityReviewsOut)
def get_clarity_reviews(
    oa_id: str, unit: Unit, results: Results, steps: Steps, runs: Runs
) -> ClarityReviewsOut:
    view = _view(oa_id, "clarity-reviews", unit, results, steps, runs)
    return _list(ClarityReviewsOut, oa_id, view)


@router.get("/oas/{oa_id}/legal-evidence", response_model=LegalEvidenceOut)
def get_legal_evidence(
    oa_id: str, unit: Unit, results: Results, steps: Steps, runs: Runs
) -> LegalEvidenceOut:
    view = _view(oa_id, "legal-evidence", unit, results, steps, runs)
    return _list(LegalEvidenceOut, oa_id, view)


@router.get("/oas/{oa_id}/directions", response_model=DirectionsOut)
def get_directions(
    oa_id: str, unit: Unit, results: Results, steps: Steps, runs: Runs
) -> DirectionsOut:
    view = _view(oa_id, "directions", unit, results, steps, runs)
    f4 = view.step_result if isinstance(view.step_result, F4Output) else None
    return _list(DirectionsOut, oa_id, view, rank_notice=f4.rank_notice if f4 else None)


@router.get("/oas/{oa_id}/drafts", response_model=DraftsOut)
def get_drafts(oa_id: str, unit: Unit, results: Results, steps: Steps, runs: Runs) -> DraftsOut:
    view = _view(oa_id, "drafts", unit, results, steps, runs)
    f4 = view.step_result if isinstance(view.step_result, F4Output) else None
    return DraftsOut(
        oa_id=oa_id,
        run_id=view.run_id,
        result=view.value,
        empty_reason=view.empty_reason,
        held_units=f4.held_units if f4 else [],
        legality_notice=f4.legality_notice if f4 else None,
    )
