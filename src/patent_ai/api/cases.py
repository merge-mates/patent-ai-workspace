"""사건 엔드포인트 (이슈 #56 T2). 라우터만 두고 검사·파일 저장은 core/cases에 있다."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel

from patent_ai.api.deps import CaseUnit, get_case_unit, get_upload_dir
from patent_ai.api.errors import AppError
from patent_ai.core.cases import upload
from patent_ai.core.cases.store import (
    DuplicateDocumentError,
    NewDocument,
    new_case_id,
    now_utc,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class OARefOut(BaseModel):
    oa_id: str
    notice_kind: str | None


class CreatedCase(BaseModel):
    case_id: str
    oa_id: str
    run_id: str


class CaseSummary(BaseModel):
    case_id: str
    case_name: str
    application_number: str | None
    latest_oa: OARefOut
    rejection_kinds: list[str]
    run_state: str
    status: str
    review_items_count: int | None  # 이 이슈에서는 늘 null (모름, 0건과 다름)
    updated_at: datetime


class CaseDetail(BaseModel):
    case_id: str
    case_name: str
    oas: list[OARefOut]


@router.post("/cases", response_model=CreatedCase, status_code=200)
def create_case(
    file: UploadFile,
    unit: Annotated[CaseUnit, Depends(get_case_unit)],
    upload_dir: Annotated[Path, Depends(get_upload_dir)],
) -> CreatedCase:
    data = file.file.read()
    try:
        sha256 = upload.check_pdf(data)
    except upload.EmptyFileError:
        raise AppError(422, "empty_file", "빈 파일입니다") from None
    except upload.NotPdfError:
        raise AppError(422, "not_pdf", "PDF 파일이 아닙니다") from None

    # 같은 파일이 어느 사건에든 있으면 새로 만들지 않고 기존 ID를 알려 준다
    existing = unit.store.find_document_by_sha256(sha256)
    if existing is not None:
        raise AppError(
            409,
            "document_already_exists",
            "이미 올린 파일입니다",
            extra={"case_id": existing.case_id, "oa_id": existing.oa_id},
        )

    case_id = new_case_id()
    target = upload.final_path(upload_dir, case_id, sha256)
    tmp: Path | None = None
    try:
        tmp = upload.write_temp(upload_dir, data)  # 1) 임시 파일
        target.parent.mkdir(parents=True, exist_ok=True)  # 폴더는 커밋 전에 (커밋 뒤 실패 줄이기)
        created = unit.store.create_case(  # 2) DB 커밋
            NewDocument(path=str(target), sha256=sha256, received_at=now_utc()), case_id=case_id
        )
        unit.commit()
    except DuplicateDocumentError:
        # 새 사건이라 DB 제약에는 안 걸린다. 저장소가 중복이라 알려 온 경우만 409로 바꾼다
        # (같은 파일을 동시에 올리면 사건이 둘 생기는 것은 알려진 한계)
        _cleanup(unit, tmp)
        raise AppError(409, "document_already_exists", "이미 올린 파일입니다") from None
    except Exception:
        # DB(또는 파일 쓰기)가 실패하면 임시 파일을 지우고 500
        logger.exception("사건 올리기 실패")
        _cleanup(unit, tmp)
        raise AppError(500, "upload_failed", "파일을 저장하지 못했습니다") from None
    try:
        upload.finalize(tmp, target)  # 3) 이름 바꾸기
    except OSError:
        # DB에는 이미 들어갔다. 파일이 없는 줄이 남으므로 로그로 알린다
        logger.exception("DB 커밋 뒤 파일 이름 바꾸기 실패: %s", target)
        _cleanup(unit, tmp)
        raise AppError(500, "upload_failed", "파일을 저장하지 못했습니다") from None
    return CreatedCase(case_id=created.case_id, oa_id=created.oa_id, run_id=created.run_id)


def _cleanup(unit: CaseUnit, tmp: Path | None) -> None:
    unit.rollback()
    if tmp is not None:
        upload.discard(tmp)


@router.get("/cases", response_model=list[CaseSummary])
def list_cases(unit: Annotated[CaseUnit, Depends(get_case_unit)]) -> list[CaseSummary]:
    return [
        CaseSummary(
            case_id=r.case_id,
            case_name=r.case_name,
            application_number=r.application_number,
            latest_oa=OARefOut(oa_id=r.latest_oa.oa_id, notice_kind=r.latest_oa.notice_kind),
            rejection_kinds=r.rejection_kinds,
            run_state=r.run_state,
            status=r.status,
            review_items_count=None,
            updated_at=r.updated_at,
        )
        for r in unit.store.list_cases()
    ]


@router.get("/cases/{case_id}", response_model=CaseDetail)
def get_case(case_id: str, unit: Annotated[CaseUnit, Depends(get_case_unit)]) -> CaseDetail:
    row = unit.store.get_case(case_id)
    if row is None:
        raise AppError(404, "case_not_found", "사건을 찾을 수 없습니다")
    return CaseDetail(
        case_id=row.case_id,
        case_name=row.case_name,
        oas=[OARefOut(oa_id=o.oa_id, notice_kind=o.notice_kind) for o in row.oas],
    )
