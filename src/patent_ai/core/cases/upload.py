"""올린 PDF 검사와 파일 저장 (이슈 #56 T2). 라우터는 이 함수들을 부르기만 한다.

저장 순서: 임시 파일 쓰기 → (부르는 쪽이) DB 커밋 → 이름 바꾸기.
DB가 실패하면 임시 파일만 지우면 되고, 이름 바꾸기 전에는 최종 자리에 반쯤 쓴 파일이 없다.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from patent_ai.core.cases.store import CaseNotFoundError, DuplicateDocumentError

logger = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"


class EmptyFileError(ValueError):
    """빈 파일 (API는 422 empty_file)."""


class NotPdfError(ValueError):
    """앞 5바이트가 %PDF- 가 아님 (API는 422 not_pdf). content-type은 안 본다."""


def check_pdf(data: bytes) -> str:
    """PDF가 맞는지 보고 sha256(16진수)을 돌려준다."""
    if not data:
        raise EmptyFileError("빈 파일")
    if not data.startswith(PDF_MAGIC):
        raise NotPdfError("PDF가 아님")
    return hashlib.sha256(data).hexdigest()


def final_path(upload_dir: Path, case_id: str, sha256: str) -> Path:
    return upload_dir / case_id / f"{sha256}.pdf"


def write_temp(upload_dir: Path, data: bytes) -> Path:
    """upload_dir 안에 임시 파일로 쓴다 (같은 디스크라 이름 바꾸기가 한 번에 끝난다)."""
    upload_dir.mkdir(parents=True, exist_ok=True)
    tmp = upload_dir / f".tmp-{uuid4().hex}"
    tmp.write_bytes(data)
    return tmp


def finalize(tmp: Path, target: Path) -> None:
    """DB 커밋이 끝난 뒤 임시 파일을 최종 자리로."""
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(tmp, target)


def discard(tmp: Path) -> None:
    tmp.unlink(missing_ok=True)


class UploadFailedError(RuntimeError):
    """파일 쓰기·DB 저장 중 실패 (API는 500 upload_failed)."""


def save_with_commit[T](
    upload_dir: Path,
    case_id: str,
    sha256: str,
    data: bytes,
    write_db: Callable[[str], T],
    commit: Callable[[], None],
    rollback: Callable[[], None],
    on_finalize_failed: Callable[[T], None] | None = None,
) -> T:
    """임시 파일 → DB 쓰기·커밋 → 이름 바꾸기. POST /cases와 POST /cases/{id}/oas가 같이 쓴다.

    write_db(path)는 DB 줄을 만들고 결과를 돌려준다. 저장소가 던진 오류(중복 등)는
    임시 파일을 지운 뒤 그대로 올려 보낸다. 그 밖의 실패는 UploadFailedError.
    on_finalize_failed(created): DB 커밋은 됐는데 이름 바꾸기가 실패했을 때 부른다
    (실행기에 못 넘길 실행이 queued로 남지 않게 부르는 쪽이 정리한다).
    """
    target = final_path(upload_dir, case_id, sha256)
    tmp: Path | None = None
    try:
        tmp = write_temp(upload_dir, data)  # 1) 임시 파일
        target.parent.mkdir(parents=True, exist_ok=True)  # 폴더는 커밋 전에 (커밋 뒤 실패 줄이기)
        created = write_db(str(target))  # 2) DB 쓰기 + 커밋
        commit()
    except Exception as e:
        rollback()
        if tmp is not None:
            discard(tmp)
        if isinstance(e, DuplicateDocumentError | CaseNotFoundError):
            raise
        logger.exception("업로드 저장 실패")
        raise UploadFailedError("저장 실패") from e
    try:
        finalize(tmp, target)  # 3) 이름 바꾸기
    except OSError as e:
        # DB에는 이미 들어갔다. 파일이 없는 줄이 남으므로 로그로 알린다
        logger.exception("DB 커밋 뒤 파일 이름 바꾸기 실패: %s", target)
        discard(tmp)
        if on_finalize_failed is not None:
            on_finalize_failed(created)
        raise UploadFailedError("이름 바꾸기 실패") from e
    return created
