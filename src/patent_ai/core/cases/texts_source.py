"""F3·F4가 읽을 글자 만들기 (이슈 #205 T2): OA 당시 청구항 판 + 최초 명세서 → F3Inputs.

- 청구항: 출원 때 판 문서(출원서)부터 심사 대상 판까지의 보정서를 차례로 적용한다 (claim_texts).
- 최초 명세서: 출원 때 판 문서(출원서)의 쪽 글자. 공개·등록공보는 AI 입력으로 쓰지 않는다.
- 판이나 문서·파일을 못 찾으면 None → F3·F4는 지금처럼 input_unverified로 넘겨진다.
  번호를 못 뽑으면 글자는 넘기되 claims_status가 unverified라 F3·F4 결과가 성공으로 보이지 않는다.
- 다시 실행할 때마다 PDF를 다시 읽는다 (claims 표에 저장하지 않음:
  로컬 PDF라 빠르고 표 쓰기가 늘지 않게).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from patent_ai.core.cases.claim_texts import claims_at_version
from patent_ai.core.f1_oa_reader.case_repository import AI_INPUT_KINDS, ClaimVersionRow
from patent_ai.core.f1_oa_reader.pages import PdfReadError, extract_pages
from patent_ai.core.f3_claim_compare.inputs import F3Inputs
from patent_ai.core.schemas.document import PageText
from patent_ai.db.models import OA, ClaimVersion, Document

logger = logging.getLogger(__name__)

ReadPages = Callable[[Path, str], PageText]


def _joined(pages: PageText) -> str:
    """쪽 글자를 줄바꿈으로 잇는다 (청구항이 다음 쪽으로 이어진다)."""
    return "\n".join(p.text for p in pages.pages)


def build_texts(
    examined: ClaimVersionRow | None,
    versions: list[ClaimVersionRow],
    paths: Mapping[str, str],
    read_pages: ReadPages = extract_pages,
) -> F3Inputs | None:
    """심사 대상 판·사건의 판 목록·문서 경로 → F3Inputs. 만들 수 없으면 None (이유는 로그)."""
    if examined is None:
        logger.warning("texts_source: 심사 대상 판을 모름")
        return None
    if examined.source_kind not in AI_INPUT_KINDS:
        logger.warning("texts_source: 심사 대상 판이 %s라 AI 입력으로 안 씀", examined.source_kind)
        return None
    # 출원 때 판(0)부터 심사 대상 판까지의 출원·보정 판 (뒤 판·공보 판은 뺀다)
    chain = sorted(
        (v for v in versions if v.source_kind in AI_INPUT_KINDS and v.version <= examined.version),
        key=lambda v: v.version,
    )
    if not chain or chain[0].source_kind != "application" or chain[-1].id != examined.id:
        logger.warning("texts_source: 출원 때 판부터 심사 대상 판까지 이어지지 않음")
        return None
    read: list[PageText] = []
    for v in chain:
        path = paths.get(v.document_id or "")
        if path is None:
            logger.warning("texts_source: 판 %d 문서가 없음", v.version)
            return None
        try:
            read.append(read_pages(Path(path), v.document_id))
        except PdfReadError as e:
            logger.warning("texts_source: 판 %d 문서를 못 읽음 (%s)", v.version, e)
            return None
    claims = claims_at_version([_joined(p) for p in read])
    return F3Inputs(
        claims_at_oa=claims.claims,
        claims_status=claims.status,
        claims_document_id=examined.document_id,
        spec=read[0],  # 최초 명세서 = 출원서
    )


class PostgresTextsSource:
    """run_inputs.TextsSource 구현: OA id → 그 OA 당시 글자. 호출마다 새 세션을 연다."""

    def __init__(
        self, session_factory: Callable[[], Session], read_pages: ReadPages = extract_pages
    ) -> None:
        self._factory = session_factory
        self._read = read_pages

    def texts_for(self, oa_id: str) -> F3Inputs | None:
        with self._factory() as s:
            oa = s.get(OA, oa_id)
            if oa is None:
                return None
            rows = s.scalars(select(ClaimVersion).where(ClaimVersion.case_id == oa.case_id)).all()
            versions = [
                ClaimVersionRow(
                    v.id, v.case_id, v.version, v.source_kind,
                    v.source_doc_number, v.case_event_id, v.document_id,
                )
                for v in rows
            ]  # fmt: skip
            doc_ids = [v.document_id for v in versions if v.document_id]
            q = select(Document.id, Document.path).where(Document.id.in_(doc_ids))
            paths = {d: p for d, p in s.execute(q).all()} if doc_ids else {}
            examined = next((v for v in versions if v.id == oa.examined_claim_version_id), None)
        # PDF 읽기는 세션을 닫은 뒤에 한다 (DB 연결을 오래 잡지 않게)
        return build_texts(examined, versions, paths, self._read)
