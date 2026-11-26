"""F3·F4가 읽을 글자 만들기 (이슈 #205 T2): OA 당시 청구항 판 + 최초 명세서 → F3Inputs.

- 청구항: 출원 때 판 문서(출원서)부터 심사 대상 판까지의 보정서를 차례로 적용한다 (claim_texts).
- 최초 명세서: 출원 때 판 문서(출원서)의 쪽 글자. 공개·등록공보는 AI 입력으로 쓰지 않는다.
- 판이나 문서·파일을 못 찾으면 None → F3·F4는 지금처럼 input_unverified로 넘겨진다.
  번호를 못 뽑으면 글자는 넘기되 claims_status가 unverified라 F3·F4 결과가 성공으로 보이지 않는다.
- 청구항 글자는 PDF에서 뽑으면 줄 폭에서 단어 한가운데가 끊긴다("지\n속적으로"). 사건의
  청구항이력(특허청 자료)에 띄어쓰기·줄바꿈만 빼고 같은 글자가 있으면 그 깨끗한 글자를 쓴다.
  내용이 조금이라도 다르면 PDF 글자를 그대로 둔다 (다른 판의 글과 섞이지 않게).
- 다시 실행할 때마다 PDF를 다시 읽는다 (claims 표에 저장하지 않음:
  로컬 PDF라 빠르고 표 쓰기가 늘지 않게).
"""

from __future__ import annotations

import html
import logging
import re
from collections.abc import Callable, Mapping
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from patent_ai.core.cases.case_source.parse import ClaimChangeRow, parse_claim_history
from patent_ai.core.cases.claim_texts import claim_region, claims_at_version
from patent_ai.core.f1_oa_reader.case_repository import AI_INPUT_KINDS, ClaimVersionRow
from patent_ai.core.f1_oa_reader.pages import PdfReadError, extract_pages
from patent_ai.core.f3_claim_compare.inputs import F3Inputs
from patent_ai.core.schemas.common import Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.document import PageText
from patent_ai.db.models import OA, Case, CaseEvent, ClaimVersion, Document

logger = logging.getLogger(__name__)

ReadPages = Callable[[Path, str], PageText]


def _joined(pages: PageText) -> str:
    """쪽 글자를 줄바꿈으로 잇는다 (청구항이 다음 쪽으로 이어진다)."""
    return "\n".join(p.text for p in pages.pages)


def _blank_page_in_claims(pages: PageText, *, first: bool) -> int | None:
    """청구항으로 읽는 글자 범위에 글자 층 없는 쪽(스캔·그림)이 끼었으면 그 쪽 번호.

    그런 쪽은 글자가 ""라 이어 붙이면 티 없이 빠진다. 쪽마다 이은 글자 안 시작 위치를 기억해
    청구항 범위와 겹치는지 본다 (리뷰 #215). 범위 밖(문서 끝 도면 쪽 등)은 상관없다.
    """
    region = claim_region(_joined(pages), first=first)
    if region is None:
        return None  # 청구항을 못 찾으면 claims_at_version이 따로 unverified로 둔다
    begin, end = region
    start = 0
    for p in pages.pages:
        stop = start + len(p.text)
        if p.status.value != StatusValue.CONFIRMED and start <= end and stop >= begin:
            return p.page
        start = stop + 1  # 쪽 사이 줄바꿈 한 글자
    return None


_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_SPACE = re.compile(r"\s+")


def _history_text(text: str) -> str:
    """청구항이력 글자: <br />는 청구항 안의 줄바꿈, HTML 문자(&lt; 등)는 글자로."""
    return html.unescape(_BR.sub("\n", text)).strip()


def _squeezed(text: str) -> str:
    return _SPACE.sub("", text)


def _clean_claims(
    claims: dict[int, str], history: list[ClaimChangeRow]
) -> tuple[dict[int, str], int]:
    """PDF 청구항마다, 띄어쓰기·줄바꿈만 빼고 같은 청구항이력 글자가 있으면 그 글자로 바꾼다.

    판을 맞추지 않고 글자로만 맞춘다: 같으면 내용이 같다는 뜻이라 어느 판 글인지 따질 필요가 없다.
    돌려주는 값: (청구항, 바꾼 개수)
    """
    by_claim: dict[int, list[str]] = {}
    for row in history:
        if row.change == "삭제" or not row.claim_no.isdigit():
            continue
        by_claim.setdefault(int(row.claim_no), []).append(_history_text(row.text))
    out: dict[int, str] = {}
    replaced = 0
    for no, text in claims.items():
        target = _squeezed(text)
        clean = next((h for h in by_claim.get(no, []) if _squeezed(h) == target), None)
        if clean is not None:
            replaced += clean != text
            out[no] = clean
        else:
            out[no] = text  # 내용이 다르거나 이력에 없으면 PDF 글자 그대로
    return out, replaced


def build_texts(
    examined: ClaimVersionRow | None,
    versions: list[ClaimVersionRow],
    paths: Mapping[str, str],
    read_pages: ReadPages = extract_pages,
    claim_history: list[ClaimChangeRow] | None = None,
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
    status = claims.status
    claim_texts = claims.claims
    if claim_history:
        # 줄바꿈으로 끊긴 PDF 글자를 청구항이력의 깨끗한 글자로 (같은 내용일 때만)
        claim_texts, replaced = _clean_claims(claim_texts, claim_history)
        logger.info(
            "texts_source: 청구항 %d개 중 %d개를 청구항이력 글자로 정리", len(claim_texts), replaced
        )
    else:
        logger.warning(
            "texts_source: 청구항이력이 없어 PDF 글자를 그대로 씀 (줄바꿈 끊김이 남을 수 있음)"
        )
    for i, pages in enumerate(read):
        blank = _blank_page_in_claims(pages, first=i == 0)
        if blank is not None:
            logger.warning(
                "texts_source: 판 %d 문서 %d쪽에 글자 층이 없음", chain[i].version, blank
            )
            status = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.BODY_MISSING)
            break
    return F3Inputs(
        claims_at_oa=claim_texts,
        claims_status=status,
        claims_document_id=examined.document_id,
        spec=read[0],  # 최초 명세서 = 출원서
    )


class PostgresTextsSource:
    """run_inputs.TextsSource 구현: OA id → 그 OA 당시 글자. 호출마다 새 세션을 연다."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        read_pages: ReadPages = extract_pages,
        claim_history: Callable[[str, str], str | None] | None = None,
    ) -> None:
        self._factory = session_factory
        self._read = read_pages
        # (출원번호, 발송번호) → 청구항이력 글. 없으면 PDF 글자만 쓴다
        self._history = claim_history

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
            case = s.get(Case, oa.case_id)
            event = s.get(CaseEvent, oa.case_event_id) if oa.case_event_id else None
            app_no = case.application_number if case else None
            dispatch = event.doc_number if event else None
        # PDF 읽기는 세션을 닫은 뒤에 한다 (DB 연결을 오래 잡지 않게)
        return build_texts(
            examined, versions, paths, self._read, self._read_history(app_no, dispatch)
        )

    def _read_history(
        self, app_no: str | None, dispatch: str | None
    ) -> list[ClaimChangeRow] | None:
        """사건 청구항이력을 읽는다. 못 읽으면 None (경고만, PDF 글자로 계속)."""
        if self._history is None or not app_no or not dispatch:
            return None
        try:
            text = self._history(app_no, dispatch)
            return parse_claim_history(text) if text else None
        except Exception as e:  # noqa: BLE001 - 이력은 덧붙이는 자료라 실패해도 실행을 막지 않는다
            logger.warning("texts_source: 청구항이력을 못 읽음 (%s)", type(e).__name__)
            return None
