"""올린 PDF 검사와 파일 저장 (이슈 #56 T2). 라우터는 이 함수들을 부르기만 한다.

저장 순서: 임시 파일 쓰기 → (부르는 쪽이) DB 커밋 → 이름 바꾸기.
DB가 실패하면 임시 파일만 지우면 되고, 이름 바꾸기 전에는 최종 자리에 반쯤 쓴 파일이 없다.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import uuid4

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
