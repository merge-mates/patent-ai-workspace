"""초안 고치기와 사건 전체 검사 엔드포인트 (이슈 #304). 판단은 core/cases/에 있다.

- PATCH /drafts/{draft_id}: 의견서 칸 또는 보정 청구항 하나를 사람이 고친다 (draft_edits.py).
  응답은 고친 초안 `Drafts` 전체 (화면 web/src/api/index.ts patchDraft가 그 모양을 받는다).
- GET /oas/{oa_id}/case-check: 사건 전체 검사 (case_check.py).
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
from patent_ai.core.cases.case_check import CaseCheck, case_check
from patent_ai.core.cases.draft_edits import (
    ClaimNotEditableError,
    DraftNotFoundError,
    InvalidDraftEditError,
    edit_draft,
)
from patent_ai.core.cases.results import OAResultStore
from patent_ai.core.cases.step_results import StepResultStore
from patent_ai.core.runs.store import RunStatusStore
from patent_ai.core.schemas.drafts import Drafts

router = APIRouter()

Results = Annotated[OAResultStore, Depends(get_oa_result_store)]
Steps = Annotated[StepResultStore, Depends(get_step_result_store)]
Runs = Annotated[RunStatusStore, Depends(get_run_status_store)]
Unit = Annotated[CaseUnit, Depends(get_case_unit)]


class DraftPatchIn(BaseModel):
    """둘 중 정확히 하나: 의견서 칸 key(section) 또는 보정 청구항 번호(claim)."""

    section: str | None = None
    claim: int | None = None
    text: str


_INVALID = "의견서 칸(section)이나 청구항 번호(claim) 하나와 비지 않은 글(text)을 보내야 합니다"


@router.patch("/drafts/{draft_id:path}", response_model=Drafts)
def patch_draft(draft_id: str, body: DraftPatchIn, results: Results, steps: Steps) -> Drafts:
    # 본문 꼴(text 없음 등)이 틀리면 공통 처리기가 422 validation_error로 답한다
    try:
        return edit_draft(
            draft_id,
            section=body.section,
            claim=body.claim,
            text=body.text,
            oa_results=results,
            step_results=steps,
        )
    except DraftNotFoundError:
        raise AppError(404, "draft_not_found", "초안을 찾을 수 없습니다") from None
    except ClaimNotEditableError:
        raise AppError(422, "claim_not_editable", "고칠 수 있는 보정 초안이 없습니다") from None
    except InvalidDraftEditError:
        raise AppError(422, "invalid_draft_edit", _INVALID) from None


@router.get("/oas/{oa_id}/case-check", response_model=CaseCheck)
def get_case_check(oa_id: str, unit: Unit, results: Results, steps: Steps, runs: Runs) -> CaseCheck:
    if unit.store.get_oa(oa_id) is None:
        raise AppError(404, "oa_not_found", "OA를 찾을 수 없습니다")
    got = case_check(oa_id, oa_results=results, step_results=steps, runs=runs)
    if got is None:
        raise AppError(404, "result_not_ready", "결과가 아직 없습니다")
    return got
