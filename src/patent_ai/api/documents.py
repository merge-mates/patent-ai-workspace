"""빠진 자료 올리기 엔드포인트 (#16 T7, 11/17 "올려 주세요"에 답함).

라우터만 둔다. 묶기·사건 자료 고치기·저장은 core 사건 저장소(case_repository)가 한다.
사건 자료 읽기(GET /cases/{id}/materials)는 #57이 맡는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, UploadFile
from pydantic import BaseModel

from patent_ai.api.cases import read_pdf
from patent_ai.api.deps import (
    CaseRepositoryUnit,
    CaseUnit,
    get_case_repository_unit,
    get_case_unit,
    get_upload_dir,
)
from patent_ai.api.errors import AppError
from patent_ai.core.cases import upload
from patent_ai.core.cases.store import now_utc
from patent_ai.core.f1_oa_reader.case_grouping import (
    MissingNotFoundError,
    UploadNotAskedError,
    missing_to_answer,
)
from patent_ai.core.f1_oa_reader.case_repository import (
    DuplicateDocumentError,
    StoredFile,
    upload_missing_material,
)
from patent_ai.core.schemas.case_materials import CaseMaterials

router = APIRouter()


class UploadedMaterialOut(BaseModel):
    case_id: str
    document_id: str  # 올린 자료의 문서 ID
    result: CaseMaterials  # 고친 사건 자료 (결과 스키마 ⑥ 그대로)


@router.post("/cases/{case_id}/documents", response_model=UploadedMaterialOut)
def upload_missing_document(
    case_id: str,
    file: UploadFile,
    what: Annotated[str, Form()],  # 답하는 빠진 자료 (CaseMaterials.missing[].what 글자 그대로)
    unit: Annotated[CaseUnit, Depends(get_case_unit)],
    cases: Annotated[CaseRepositoryUnit, Depends(get_case_repository_unit)],
    upload_dir: Annotated[Path, Depends(get_upload_dir)],
) -> UploadedMaterialOut:
    # 1) 사건과 사건 자료가 있는지 본다. 사건은 있는데 자료가 아직 없으면 result_not_ready
    materials = cases.repo.load_case_materials(case_id)
    if materials is None:
        if unit.store.get_case(case_id) is None:
            raise AppError(404, "case_not_found", "사건을 찾을 수 없습니다")
        raise AppError(404, "result_not_ready", "사건 자료가 아직 없습니다")

    # 2) 파일을 쓰기 전에 요청을 검사한다 (PDF인지, 빠진 자료에 답하는지)
    data, sha256 = read_pdf(file)
    try:
        missing_to_answer(materials, what)
    except MissingNotFoundError:
        raise AppError(422, "missing_not_found", "빠진 자료 목록에 없는 자료입니다") from None
    except UploadNotAskedError:
        raise AppError(
            422, "upload_not_asked", "직접 확인할 자료라 올리기를 받지 않습니다"
        ) from None

    # 3) 임시 파일 → 묶기·사건 자료 고치기·저장 + 커밋 → 이름 바꾸기
    try:
        updated, document_id = upload.save_with_commit(
            upload_dir,
            case_id,
            sha256,
            data,
            lambda path: _save(cases, case_id, what, path, sha256),
            cases.commit,
            cases.rollback,
        )
    except DuplicateDocumentError:
        raise AppError(
            409,
            "document_already_exists",
            "이미 올린 파일입니다",
            extra={"case_id": case_id},
        ) from None
    except upload.UploadFailedError:
        raise AppError(500, "upload_failed", "파일을 저장하지 못했습니다") from None
    return UploadedMaterialOut(case_id=case_id, document_id=document_id, result=updated)


def _save(
    cases: CaseRepositoryUnit, case_id: str, what: str, path: str, sha256: str
) -> tuple[CaseMaterials, str]:
    file = StoredFile(path=path, sha256=sha256, received_at=now_utc())
    updated = upload_missing_material(cases.repo, case_id, what, file)
    return updated, updated.documents[-1].document_id
