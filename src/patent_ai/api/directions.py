"""사람이 대응 방향을 고르는 엔드포인트 (이슈 #70). 판단은 core/cases/select_direction.py에 있다.

PUT /directions/{unit_id}/selection: 후보를 고르거나(candidate_id) 직접 쓴 방향(written_direction)을
받아 기록하고, 초안만 다시 만드는 작은 실행을 시작한다. 화면은 응답 run_id를 폴링한다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from patent_ai.api.deps import (
    CaseUnit,
    get_case_unit,
    get_oa_result_store,
    get_run_launcher,
    get_run_status_store,
    get_selection_store,
    get_step_result_store,
)
from patent_ai.api.errors import AppError
from patent_ai.api.runs import launch_run
from patent_ai.core.cases.results import OAResultStore
from patent_ai.core.cases.select_direction import (
    CandidateNotFoundError,
    InvalidSelectionError,
    ResultNotReadyError,
    UnitNotFoundError,
    select_direction,
)
from patent_ai.core.cases.selections import SelectionStore
from patent_ai.core.cases.start_run import OANotFoundError, RunInProgressError
from patent_ai.core.cases.step_results import StepResultStore
from patent_ai.core.runs.launcher import RunLauncher
from patent_ai.core.runs.store import RunStatusStore
from patent_ai.core.schemas.direction import DirectionSelection

router = APIRouter()


class SelectionIn(BaseModel):
    """둘 중 정확히 하나: 후보 id 또는 사람이 직접 쓴 방향 글."""

    candidate_id: str | None = None
    written_direction: str | None = None


class SelectionOut(BaseModel):
    unit_id: str
    run_id: str  # 초안만 다시 만드는 작은 실행 (화면은 이것을 폴링)
    selection: DirectionSelection


@router.put("/directions/{unit_id:path}/selection", response_model=SelectionOut)
def put_selection(
    unit_id: str,
    body: SelectionIn,
    unit: Annotated[CaseUnit, Depends(get_case_unit)],
    oa_results: Annotated[OAResultStore, Depends(get_oa_result_store)],
    step_results: Annotated[StepResultStore, Depends(get_step_result_store)],
    selections: Annotated[SelectionStore, Depends(get_selection_store)],
    launch: Annotated[RunLauncher, Depends(get_run_launcher)],
    status_store: Annotated[RunStatusStore, Depends(get_run_status_store)],
) -> SelectionOut:
    try:
        made = select_direction(
            unit_id,
            candidate_id=body.candidate_id,
            written_direction=body.written_direction,
            store=unit.store,
            oa_results=oa_results,
            step_results=step_results,
            selections=selections,
        )
    except OANotFoundError:
        raise AppError(404, "oa_not_found", "OA를 찾을 수 없습니다") from None
    except UnitNotFoundError:
        raise AppError(404, "unit_not_found", "판단 단위를 찾을 수 없습니다") from None
    except ResultNotReadyError:
        raise AppError(404, "result_not_ready", "고를 방향 후보가 아직 없습니다") from None
    except RunInProgressError:
        raise AppError(409, "run_in_progress", "이미 진행 중인 실행이 있습니다") from None
    except CandidateNotFoundError:
        raise AppError(422, "candidate_not_found", "그 묶음의 후보가 아닙니다") from None
    except InvalidSelectionError:
        raise AppError(
            422, "invalid_selection", "후보 id나 직접 쓴 방향 중 하나만 보내야 합니다"
        ) from None
    unit.commit()  # 커밋해야 실행기(다른 세션)가 이 실행 줄을 본다
    launch_run(launch, status_store, made.run.id, made.oa_id)
    return SelectionOut(unit_id=made.unit_id, run_id=made.run.id, selection=made.selection)
