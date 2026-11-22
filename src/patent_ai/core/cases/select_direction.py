"""사람이 대응 방향을 고르는 판단 (이슈 #70). 라우터(api/directions.py)는 이 함수를 부르기만 한다.

PUT /directions/{unit_id}/selection:
1. unit_id(`OA ID:조문:c대표 청구항`)에서 OA를 찾고, 그 OA에 진행 중 실행이 있으면 막는다.
2. 보여 줄 실행의 F4 결과에서 그 묶음과 후보를 찾는다 (없으면 고를 것이 없다).
3. 사람 선택을 기록(direction_selections)에 쌓고, 초안만 다시 만드는 작은 실행(redo_drafts)을
   만든다.
   실행기가 그 실행에서 앞 결과 + 가장 최근 선택으로 초안을 다시 만든다 (run_case_executor).
확신 낮은 묶음은 사람이 고르기 전까지 초안이 없다 (F4가 보류, 서버는 이 길로만 선택을 받는다).
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from patent_ai.core.cases.results import OAResultStore
from patent_ai.core.cases.selections import SelectionStore
from patent_ai.core.cases.start_run import OANotFoundError, RunInProgressError, has_active_run
from patent_ai.core.cases.step_results import StepResultStore
from patent_ai.core.cases.store import CaseAppStore, RunRow
from patent_ai.core.f4_response_draft.result import F4Output
from patent_ai.core.schemas.common import Origin
from patent_ai.core.schemas.direction import DirectionSelection

REDO_DRAFTS = "redo_drafts"


class ResultNotReadyError(LookupError):
    """고를 방향 후보가 아직 없다 (API는 404 result_not_ready)."""


class UnitNotFoundError(LookupError):
    """그 OA의 F4 결과에 그 묶음이 없다 (API는 404 unit_not_found)."""


class CandidateNotFoundError(ValueError):
    """그 묶음 후보에 없는 candidate_id (API는 422 candidate_not_found)."""


class InvalidSelectionError(ValueError):
    """후보 id와 직접 쓴 글 중 정확히 하나가 아니거나 글이 비었다 (API는 422 invalid_selection)."""


@dataclass(frozen=True)
class SelectionMade:
    oa_id: str
    unit_id: str
    selection: DirectionSelection
    run: RunRow  # 초안만 다시 만드는 작은 실행 (queued)


def oa_id_of_unit(unit_id: str) -> str:
    """unit_id 맨 앞 칸이 OA ID다 (data-model 4절 ②: `OA ID:조문:c대표 청구항`)."""
    return unit_id.split(":", 1)[0]


def _selection(candidate_id: str | None, written_direction: str | None) -> DirectionSelection:
    """요청 본문을 사람 선택으로. 둘 중 하나만, 빈 글 거부는 스키마 검사에 맡긴다."""
    origin = Origin.HUMAN_WRITTEN if written_direction is not None else Origin.HUMAN_SELECTED
    try:
        return DirectionSelection(
            candidate_id=candidate_id, written_direction=written_direction, origin=origin
        )
    except ValidationError as e:
        raise InvalidSelectionError("후보 id나 직접 쓴 방향 중 하나만 보내야 합니다") from e


def select_direction(
    unit_id: str,
    *,
    candidate_id: str | None,
    written_direction: str | None,
    store: CaseAppStore,
    oa_results: OAResultStore,
    step_results: StepResultStore,
    selections: SelectionStore,
) -> SelectionMade:
    oa_id = oa_id_of_unit(unit_id)
    oa = store.get_oa(oa_id)
    if oa is None:
        raise OANotFoundError(oa_id)
    # 도는 실행이 있으면 그 실행이 앞 결과를 덮을 수 있어 받지 않는다 (끝난 뒤 다시 고른다)
    if has_active_run(oa.latest_run.state if oa.latest_run else None):
        raise RunInProgressError(oa_id)
    selection = _selection(candidate_id, written_direction)

    saved = oa_results.latest_visible_oa_result(oa_id)
    f4 = step_results.step_result(saved.run_id, "f4") if saved else None
    if not isinstance(f4, F4Output):
        raise ResultNotReadyError(oa_id)
    unit = next((d for d in f4.directions if d.unit_id == unit_id), None)
    if unit is None:
        raise UnitNotFoundError(unit_id)
    if candidate_id is not None and candidate_id not in {c.candidate_id for c in unit.candidates}:
        raise CandidateNotFoundError(candidate_id)

    selections.save_selection(oa_id, unit_id, selection)
    run = store.create_run(oa_id, kind=REDO_DRAFTS)
    return SelectionMade(oa_id=oa_id, unit_id=unit_id, selection=selection, run=run)
