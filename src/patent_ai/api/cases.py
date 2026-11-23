"""사건 엔드포인트 (이슈 #56 T2). 라우터만 두고 검사·파일 저장은 core/cases에 있다."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, UploadFile
from pydantic import BaseModel

from patent_ai.api.deps import (
    CaseRepositoryUnit,
    CaseUnit,
    get_case_materials_store,
    get_case_repository_unit,
    get_case_unit,
    get_run_launcher,
    get_run_status_store,
    get_upload_dir,
)
from patent_ai.api.errors import AppError
from patent_ai.api.runs import launch_run
from patent_ai.core.cases import upload
from patent_ai.core.cases.case_fill import materials_not_ready_message, merged_message
from patent_ai.core.cases.materials import CaseMaterialsStore
from patent_ai.core.cases.store import (
    NO_APPLICATION_NUMBER_NAME,
    DuplicateDocumentError,
    NewDocument,
    new_case_id,
    now_utc,
)
from patent_ai.core.f1_oa_reader.case_repository import load_case_view
from patent_ai.core.runs.launcher import RunLauncher, mark_launch_failed
from patent_ai.core.runs.store import RunStatusStore
from patent_ai.core.schemas.case_materials import CaseMaterials
from patent_ai.core.schemas.common import ExtractedValue

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


class CaseOAOut(OARefOut):
    # 그 OA의 심사 대상 판 (값 = 만든 보정서 접수번호, 출원 때 판은 "as_filed").
    # 묶기 결과가 아직 저장되지 않았으면 null (모름. 판을 확인 못 했다는 unverified와 다름)
    examined_claim_version: ExtractedValue[str] | None = None


class CaseEventOut(BaseModel):
    kind: str  # oa | amendment | opinion | registration_decision | rejection_decision | other
    doc_number: str | None  # OA는 발송번호, 보정서·의견서는 접수번호 (숫자만)
    seq: int | None  # 행정 이력 순서 (1부터). 이력에 없고 자료로만 온 줄은 null


class ClaimVersionOut(BaseModel):
    version: int  # 0 = 출원 때 판
    source_kind: str  # application | amendment | publication | registration
    source_doc_number: str | None  # 보정서 판은 접수번호, 공보 판은 공개·등록번호
    document_id: str | None


class CaseDetail(BaseModel):
    case_id: str
    case_name: str
    oas: list[CaseOAOut]
    # 같은 출원번호 사건에 합쳐진 임시 사건이면 그 사건 id (#272). 화면은 그 사건을 연다
    merged_into_case_id: str | None = None
    # 아래는 묶기 결과(#16)가 저장된 뒤에 채워진다. 그 전에는 빈 목록
    events: list[CaseEventOut] = []
    claim_versions: list[ClaimVersionOut] = []


class CaseMaterialsOut(BaseModel):
    case_id: str
    run_id: str | None  # 이 줄을 마지막으로 쓴 실행 (자료만 더했으면 null)
    result: CaseMaterials  # 결과 스키마 ⑥ 그대로


def read_pdf(file: UploadFile) -> tuple[bytes, str]:
    """올린 파일을 읽고 PDF인지 본다 (두 업로드 엔드포인트 공용). 실패는 422."""
    data = file.file.read()
    try:
        return data, upload.check_pdf(data)
    except upload.EmptyFileError:
        raise AppError(422, "empty_file", "빈 파일입니다") from None
    except upload.NotPdfError:
        raise AppError(422, "not_pdf", "PDF 파일이 아닙니다") from None


@router.post("/cases", response_model=CreatedCase, status_code=200)
def create_case(
    file: UploadFile,
    unit: Annotated[CaseUnit, Depends(get_case_unit)],
    upload_dir: Annotated[Path, Depends(get_upload_dir)],
    launch: Annotated[RunLauncher, Depends(get_run_launcher)],
    status_store: Annotated[RunStatusStore, Depends(get_run_status_store)],
) -> CreatedCase:
    data, sha256 = read_pdf(file)

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
    try:
        created = upload.save_with_commit(
            upload_dir,
            case_id,
            sha256,
            data,
            lambda path: unit.store.create_case(
                NewDocument(path=path, sha256=sha256, received_at=now_utc()), case_id=case_id
            ),
            unit.commit,
            unit.rollback,
            lambda c: mark_launch_failed(
                status_store, c.run_id, "파일 저장을 마치지 못해 실행하지 않았습니다"
            ),
        )
    except DuplicateDocumentError:
        # 새 사건이라 DB 제약에는 안 걸린다. 저장소가 중복이라 알려 온 경우만 409로 바꾼다
        # (같은 파일을 동시에 올리면 사건이 둘 생기는 것은 알려진 한계)
        # 기존 ID를 모르는 경우라 README 2절 칸 모양만 맞춰 null로 둔다
        raise AppError(
            409,
            "document_already_exists",
            "이미 올린 파일입니다",
            extra={"case_id": None, "oa_id": None},
        ) from None
    except upload.UploadFailedError:
        raise AppError(500, "upload_failed", "파일을 저장하지 못했습니다") from None
    launch_run(launch, status_store, created.run_id, created.oa_id)  # 커밋 뒤에 실행기에 넘긴다
    return CreatedCase(case_id=created.case_id, oa_id=created.oa_id, run_id=created.run_id)


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
def get_case(
    case_id: str,
    unit: Annotated[CaseUnit, Depends(get_case_unit)],
    cases: Annotated[CaseRepositoryUnit, Depends(get_case_repository_unit)],
) -> CaseDetail:
    row = unit.store.get_case(case_id)
    if row is None:
        raise AppError(404, "case_not_found", "사건을 찾을 수 없습니다")
    # OA별 심사 대상 판은 묶기 결과의 OA 줄에서 oa_id로 찾는다 (같은 oas 표)
    # 이력·청구항 판은 가장 늦게 올라온 OA 시점까지 자른 것 (core가 자름, design 3-3)
    view = load_case_view(cases.repo, case_id)
    examined = {v.oa_id: v.examined_claim_version for v in view.oa_versions}
    return CaseDetail(
        case_id=row.case_id,
        case_name=row.case_name,
        merged_into_case_id=row.merged_into,
        oas=[
            CaseOAOut(
                oa_id=o.oa_id,
                notice_kind=o.notice_kind,
                examined_claim_version=examined.get(o.oa_id),
            )
            for o in row.oas
        ],
        events=[CaseEventOut(kind=e.kind, doc_number=e.doc_number, seq=e.seq) for e in view.events],
        claim_versions=[
            ClaimVersionOut(
                version=v.version,
                source_kind=v.source_kind,
                source_doc_number=v.source_doc_number,
                document_id=v.document_id,
            )
            for v in view.claim_versions
        ],
    )


@router.get("/cases/{case_id}/materials", response_model=CaseMaterialsOut)
def get_case_materials(
    case_id: str,
    unit: Annotated[CaseUnit, Depends(get_case_unit)],
    materials: Annotated[CaseMaterialsStore, Depends(get_case_materials_store)],
) -> CaseMaterialsOut:
    row = unit.store.get_case(case_id)
    if row is None:
        raise AppError(404, "case_not_found", "사건을 찾을 수 없습니다")
    if row.merged_into is not None:
        raise AppError(404, "result_not_ready", merged_message(row.merged_into))
    saved = materials.latest_case_materials(case_id)
    if saved is None:
        # 이유 없는 404가 되지 않게: 출원번호를 모르면 그 이유를 메시지에 (#261)
        known = row.case_name != NO_APPLICATION_NUMBER_NAME
        raise AppError(404, "result_not_ready", materials_not_ready_message(known))
    return CaseMaterialsOut(case_id=case_id, run_id=saved.run_id, result=saved.result)
