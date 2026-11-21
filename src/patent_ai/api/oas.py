"""OA 엔드포인트 (이슈 #56 T3). 검사·파일 저장은 사건 올리기와 같은 core/cases/upload.py를 쓴다."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel

from patent_ai.api.cases import read_pdf
from patent_ai.api.deps import CaseUnit, get_case_unit, get_run_launcher, get_upload_dir
from patent_ai.api.errors import AppError
from patent_ai.core.cases import upload
from patent_ai.core.cases.store import (
    CaseNotFoundError,
    DuplicateDocumentError,
    NewDocument,
    now_utc,
)
from patent_ai.core.runs.launcher import RunLauncher

router = APIRouter()


class CreatedOA(BaseModel):
    oa_id: str
    run_id: str


class LatestRun(BaseModel):
    run_id: str
    state: str
    current_step: str | None


class OADetail(BaseModel):
    oa_id: str
    case_id: str
    case_name: str
    document_id: str | None
    latest_run: LatestRun | None
    dispatch_number: str | None  # 모르면 null (F1이 읽은 뒤 채워진다)


@router.post("/cases/{case_id}/oas", response_model=CreatedOA)
def add_oa(
    case_id: str,
    file: UploadFile,
    unit: Annotated[CaseUnit, Depends(get_case_unit)],
    upload_dir: Annotated[Path, Depends(get_upload_dir)],
    launch: Annotated[RunLauncher, Depends(get_run_launcher)],
) -> CreatedOA:
    # 없는 사건이면 파일을 읽기 전에 404
    if unit.store.get_case(case_id) is None:
        raise AppError(404, "case_not_found", "사건을 찾을 수 없습니다")
    data, sha256 = read_pdf(file)
    try:
        created = upload.save_with_commit(
            upload_dir,
            case_id,
            sha256,
            data,
            lambda path: unit.store.add_oa(
                case_id, NewDocument(path=path, sha256=sha256, received_at=now_utc())
            ),
            unit.commit,
            unit.rollback,
        )
    except CaseNotFoundError:
        raise AppError(404, "case_not_found", "사건을 찾을 수 없습니다") from None
    except DuplicateDocumentError:
        # 같은 사건 안 중복만 막는다 (다른 사건에 있는 파일은 다음 OA로 올릴 수 있다).
        # 기존 OA ID는 이 사건 안에서 찾아 담는다
        found = unit.store.find_document_by_sha256(sha256, case_id=case_id)
        raise AppError(
            409,
            "document_already_exists",
            "이미 올린 파일입니다",
            extra={"case_id": case_id, "oa_id": found.oa_id if found else None},
        ) from None
    except upload.UploadFailedError:
        raise AppError(500, "upload_failed", "파일을 저장하지 못했습니다") from None
    launch(created.run_id, created.oa_id)  # 커밋 뒤에 실행기에 넘긴다
    return CreatedOA(oa_id=created.oa_id, run_id=created.run_id)


@router.get("/oas/{oa_id}", response_model=OADetail)
def get_oa(oa_id: str, unit: Annotated[CaseUnit, Depends(get_case_unit)]) -> OADetail:
    row = unit.store.get_oa(oa_id)
    if row is None:
        raise AppError(404, "oa_not_found", "OA를 찾을 수 없습니다")
    run = row.latest_run
    return OADetail(
        oa_id=row.oa_id,
        case_id=row.case_id,
        case_name=row.case_name,
        document_id=row.document_id,
        latest_run=LatestRun(run_id=run.id, state=run.state, current_step=run.current_step)
        if run
        else None,
        dispatch_number=row.dispatch_number,
    )
