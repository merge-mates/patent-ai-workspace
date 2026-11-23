"""실행 엔드포인트 (이슈 #57). 라우터만 두고 판단은 core/cases/start_run.py, core/runs/에 있다."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from patent_ai.api.deps import (
    CaseUnit,
    get_cancel_registry,
    get_case_unit,
    get_run_launcher,
    get_run_status_store,
)
from patent_ai.api.errors import AppError
from patent_ai.core.cases.start_run import OANotFoundError, RunInProgressError, create_run_for_oa
from patent_ai.core.cases.store import CaseAppStore
from patent_ai.core.runs.cancel import CancelRegistry, RunAlreadyFinished, request_cancel
from patent_ai.core.runs.launcher import LaunchFailedError, RunLauncher, launch_or_fail
from patent_ai.core.runs.store import RunNotFound, RunStatus, RunStatusStore
from patent_ai.core.runs.warnings import skipped_step_warnings

router = APIRouter()


class RunCreated(BaseModel):
    run_id: str


class RunErrorOut(BaseModel):
    code: str
    message: str


class SkippedStepOut(BaseModel):
    step: str
    reason: str


class RunWarningOut(BaseModel):
    code: str
    message: str


class RunStatusOut(BaseModel):
    run_id: str
    oa_id: str
    # 그 OA가 지금 속한 사건. 같은 출원번호 사건에 합쳐지면 합친 사건 id (#272, 화면이 연다)
    case_id: str | None = None
    state: str
    current_step: str | None
    waiting_for: str | None = None  # 사람을 기다릴 때만
    error: RunErrorOut | None  # 실패했을 때만 {code, message}
    skipped_steps: list[SkippedStepOut] = []  # 자료·도구가 없어 넘긴 단계
    warnings: list[
        RunWarningOut
    ] = []  # 넘긴 단계마다 step_skipped 하나 (호출 상한 이유면 limit_reached)


def _out(s: RunStatus, store: RunStatusStore, cases: CaseAppStore) -> RunStatusOut:
    skipped = store.skipped_steps(s.run_id)
    oa = cases.get_oa(s.oa_id)
    return RunStatusOut(
        run_id=s.run_id,
        oa_id=s.oa_id,
        case_id=oa.case_id if oa else None,
        state=s.state.value,
        current_step=s.current_step,
        waiting_for=s.waiting_for,
        error=RunErrorOut(**s.error) if s.error else None,
        skipped_steps=[SkippedStepOut(step=k.step, reason=k.reason) for k in skipped],
        warnings=[
            RunWarningOut(code=w.code, message=w.message) for w in skipped_step_warnings(skipped)
        ],
    )


def launch_run(launch: RunLauncher, store: RunStatusStore, run_id: str, oa_id: str) -> None:
    """커밋 뒤에 실행기에 넘긴다. 못 넘기면 실행을 failed로 남기고 500 launch_failed."""
    try:
        launch_or_fail(launch, store, run_id, oa_id)
    except LaunchFailedError:
        raise AppError(500, "launch_failed", "실행을 시작하지 못했습니다") from None


@router.post("/oas/{oa_id}/runs", response_model=RunCreated)
def create_run(
    oa_id: str,
    unit: Annotated[CaseUnit, Depends(get_case_unit)],
    launch: Annotated[RunLauncher, Depends(get_run_launcher)],
    status_store: Annotated[RunStatusStore, Depends(get_run_status_store)],
) -> RunCreated:
    try:
        run = create_run_for_oa(unit.store, oa_id)
    except OANotFoundError:
        raise AppError(404, "oa_not_found", "OA를 찾을 수 없습니다") from None
    except RunInProgressError:
        raise AppError(409, "run_in_progress", "이미 진행 중인 실행이 있습니다") from None
    unit.commit()  # 커밋해야 실행기(다른 세션)가 이 줄을 본다
    launch_run(launch, status_store, run.id, oa_id)
    return RunCreated(run_id=run.id)


@router.get("/runs/{run_id}", response_model=RunStatusOut)
def get_run(
    run_id: str,
    store: Annotated[RunStatusStore, Depends(get_run_status_store)],
    unit: Annotated[CaseUnit, Depends(get_case_unit)],
) -> RunStatusOut:
    status = store.get_status(run_id)
    if status is None:
        raise AppError(404, "run_not_found", "실행을 찾을 수 없습니다")
    return _out(status, store, unit.store)


@router.post("/runs/{run_id}/cancel", response_model=RunStatusOut)
def cancel_run(
    run_id: str,
    store: Annotated[RunStatusStore, Depends(get_run_status_store)],
    registry: Annotated[CancelRegistry, Depends(get_cancel_registry)],
    unit: Annotated[CaseUnit, Depends(get_case_unit)],
) -> RunStatusOut:
    try:
        # queued·waiting_for_human은 바로 cancelled, running은 표시만 (응답 state는 running 그대로)
        return _out(request_cancel(run_id, store, registry), store, unit.store)
    except RunNotFound:
        raise AppError(404, "run_not_found", "실행을 찾을 수 없습니다") from None
    except RunAlreadyFinished:
        raise AppError(409, "run_already_finished", "이미 끝난 실행입니다") from None
