"""사람이 답하는 엔드포인트 (이슈 #70 계획 ②). 판단은 core/cases/human_answers.py에 있다.

- PATCH /cases/{id} {application_number}, PATCH /oas/{id} {dispatch_number}: 번호를 기다리는 실행에
  번호를 넣고 그 실행을 이어 돌린다. 화면은 응답 run_id를 폴링한다.
- PUT·GET /oas/{id}/oa-result/confirmation: 정리 결과 "맞아요" 남기기·보기.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from patent_ai.api.deps import (
    CaseUnit,
    get_case_unit,
    get_human_input_store,
    get_oa_result_store,
    get_run_launcher,
    get_run_status_store,
)
from patent_ai.api.errors import AppError
from patent_ai.api.runs import launch_run
from patent_ai.core.cases.human_answers import (
    Confirmation,
    HumanInputNotSavedError,
    InvalidNumberError,
    NotWaitingError,
    ResultNotReadyError,
    StaleResultError,
    confirm_oa_result,
    enter_application_number,
    enter_dispatch_number,
    oa_result_confirmation,
)
from patent_ai.core.cases.human_inputs import HumanInputStore
from patent_ai.core.cases.results import OAResultStore
from patent_ai.core.cases.start_run import OANotFoundError
from patent_ai.core.cases.store import CaseNotFoundError
from patent_ai.core.runs.launcher import RunLauncher
from patent_ai.core.runs.store import RunStatusStore

router = APIRouter()

Unit = Annotated[CaseUnit, Depends(get_case_unit)]
Runs = Annotated[RunStatusStore, Depends(get_run_status_store)]
Human = Annotated[HumanInputStore, Depends(get_human_input_store)]
Launch = Annotated[RunLauncher, Depends(get_run_launcher)]
Results = Annotated[OAResultStore, Depends(get_oa_result_store)]

_NOT_WAITING = "그 번호를 기다리는 실행이 없습니다"

logger = logging.getLogger(__name__)


def _not_saved(exc: HumanInputNotSavedError) -> AppError:
    # 저장 실패 원인은 로그에만 남긴다. 실행은 다시 번호를 기다리니 다시 넣으면 된다 (#287)
    logger.error("번호 기록 저장 실패: run_id=%s", exc, exc_info=exc.__cause__)
    return AppError(500, "human_input_not_saved", "번호를 저장하지 못했습니다. 다시 넣어 주세요")


class ApplicationNumberIn(BaseModel):
    application_number: str


class DispatchNumberIn(BaseModel):
    dispatch_number: str


class NumberEnteredOut(BaseModel):
    case_id: str
    oa_id: str
    run_id: str  # 이어 도는 실행


class ConfirmationIn(BaseModel):
    run_id: str  # 사람이 화면에서 본 OA 정리를 낸 실행


class ConfirmationOut(BaseModel):
    oa_id: str
    run_id: str  # 확인한(또는 지금 보이는) OA 정리를 낸 실행
    confirmed_at: datetime | None  # 확인 전이면 null


@router.patch("/cases/{case_id}", response_model=NumberEnteredOut)
def patch_case(
    case_id: str, body: ApplicationNumberIn, unit: Unit, runs: Runs, human: Human, launch: Launch
) -> NumberEnteredOut:
    try:
        got = enter_application_number(
            case_id, body.application_number, store=unit.store, runs=runs, human=human
        )
    except CaseNotFoundError:
        raise AppError(404, "case_not_found", "사건을 찾을 수 없습니다") from None
    except InvalidNumberError:
        raise AppError(422, "invalid_application_number", "출원번호 꼴이 아닙니다") from None
    except NotWaitingError:
        raise AppError(409, "not_waiting", _NOT_WAITING) from None
    except HumanInputNotSavedError as exc:
        raise _not_saved(exc) from exc
    launch_run(launch, runs, got.run_id, got.oa_id)
    return NumberEnteredOut(case_id=got.case_id, oa_id=got.oa_id, run_id=got.run_id)


@router.patch("/oas/{oa_id}", response_model=NumberEnteredOut)
def patch_oa(
    oa_id: str, body: DispatchNumberIn, unit: Unit, runs: Runs, human: Human, launch: Launch
) -> NumberEnteredOut:
    try:
        got = enter_dispatch_number(
            oa_id, body.dispatch_number, store=unit.store, runs=runs, human=human
        )
    except OANotFoundError:
        raise AppError(404, "oa_not_found", "OA를 찾을 수 없습니다") from None
    except InvalidNumberError:
        raise AppError(422, "invalid_dispatch_number", "발송번호 꼴이 아닙니다") from None
    except NotWaitingError:
        raise AppError(409, "not_waiting", _NOT_WAITING) from None
    except HumanInputNotSavedError as exc:
        raise _not_saved(exc) from exc
    launch_run(launch, runs, got.run_id, got.oa_id)
    return NumberEnteredOut(case_id=got.case_id, oa_id=got.oa_id, run_id=got.run_id)


def _confirmation(
    call, oa_id: str, unit: Unit, results: Results, human: Human, **kw
) -> Confirmation:
    try:
        return call(oa_id, store=unit.store, oa_results=results, human=human, **kw)
    except OANotFoundError:
        raise AppError(404, "oa_not_found", "OA를 찾을 수 없습니다") from None
    except ResultNotReadyError:
        raise AppError(404, "result_not_ready", "확인할 OA 정리가 아직 없습니다") from None
    except StaleResultError:
        # 보던 정리가 그 사이 바뀜: 확인을 남기지 않고 새 정리를 다시 보게 한다
        raise AppError(
            409, "stale_result", "보던 정리가 바뀌었습니다. 새 정리를 보고 다시 확인해 주세요"
        ) from None


@router.put("/oas/{oa_id}/oa-result/confirmation", response_model=ConfirmationOut)
def put_confirmation(
    oa_id: str, body: ConfirmationIn, unit: Unit, results: Results, human: Human
) -> ConfirmationOut:
    c = _confirmation(confirm_oa_result, oa_id, unit, results, human, seen_run_id=body.run_id)
    return ConfirmationOut(oa_id=c.oa_id, run_id=c.run_id, confirmed_at=c.confirmed_at)


@router.get("/oas/{oa_id}/oa-result/confirmation", response_model=ConfirmationOut)
def get_confirmation(oa_id: str, unit: Unit, results: Results, human: Human) -> ConfirmationOut:
    c = _confirmation(oa_result_confirmation, oa_id, unit, results, human)
    return ConfirmationOut(oa_id=c.oa_id, run_id=c.run_id, confirmed_at=c.confirmed_at)
