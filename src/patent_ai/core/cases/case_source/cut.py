"""OA 시점 자르기와 조회 한 번 (이슈 #54). 구현(local_folder·KIPRIS) 밖에서 늘 돈다.

자르는 규칙 (날짜로 자르지 않는다. scripts/split_cases_at_oa.py와 같은 줄 순서 규칙):
- 행정 이력: 줄 순서로 대상 OA(발송번호) 줄까지 남긴다. 뒤 줄은 버린다.
- 청구항 이력: 남은 행정 이력에 나온 접수번호의 줄만 남긴다 (뒤 보정 판·등록 판이 빠진다).
- 이력 줄 종류: 의견제출통지서 → oa, 청구항을 바꾼 보정서 → amendment (청구항이 안 바뀐
  보정서는 판을 만들지 않아 other), 의견서 → opinion, 그 밖 → other.
  청구항 이력을 못 가져왔으면 보정서를 모두 amendment로 본다 (출원 때 판으로 잘못 고르지 않게).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from patent_ai.core.cases.case_source.base import CaseSource, Missing
from patent_ai.core.cases.case_source.parse import (
    AdminRow,
    ClaimChangeRow,
    SourceFormatError,
    parse_admin_history,
    parse_claim_history,
)
from patent_ai.core.f1_oa_reader.case_grouping import (
    HistoryEvent,
    HistoryKind,
    NumberKind,
    read_number,
)
from patent_ai.core.schemas.common import UnverifiedReason

logger = logging.getLogger(__name__)

OA_DOC_NAME = "의견제출통지서"


@dataclass(frozen=True)
class CaseAtOA:
    """대상 OA 시점까지 자른 이력."""

    admin: list[AdminRow]  # 대상 OA 줄까지 (마지막 줄 = 대상 OA)
    claim_changes: list[ClaimChangeRow]  # 남은 접수번호의 청구항 변경만
    history: list[HistoryEvent]  # admin과 같은 순서


def _number(kind: NumberKind, text: str) -> str | None:
    return read_number(kind, text).value


def _receipt(text: str) -> str:
    """행정 이력·청구항 이력을 맞출 번호. 접수번호 꼴이면 숫자만, 아니면 글자 그대로."""
    return _number("receipt", text) or text.strip()


def _is_oa(row: AdminRow) -> bool:
    return row.name.strip() == OA_DOC_NAME


def _kind(row: AdminRow, claim_receipts: set[str] | None) -> HistoryKind:
    """이력 줄 종류. claim_receipts: 청구항을 바꾼 접수번호 (모르면 None)."""
    name = row.name
    if _is_oa(row):
        return "oa"
    if "보정서" in name and "각하" not in name:
        if claim_receipts is None or _receipt(row.number) in claim_receipts:
            return "amendment"
        return "other"  # 명세서·서식만 고친 보정: 청구항 판을 만들지 않는다
    if "의견서" in name and "통지" not in name:
        return "opinion"
    if "등록결정" in name:
        return "registration_decision"
    if "거절결정" in name:
        return "rejection_decision"
    return "other"


def cut_at_oa(
    admin: list[AdminRow],
    claims: list[ClaimChangeRow] | None,
    dispatch_number: str,
) -> CaseAtOA | Missing:
    """대상 OA 시점까지 자른다. 대상 OA를 정할 수 없으면 Missing(admin_history)."""
    target = _number("dispatch", dispatch_number)
    if target is None:
        return Missing("admin_history", UnverifiedReason.INPUT_UNVERIFIED, "발송번호 꼴이 아님")
    positions = [
        i for i, r in enumerate(admin) if _is_oa(r) and _number("dispatch", r.number) == target
    ]
    if not positions:
        return Missing(
            "admin_history", UnverifiedReason.LOOKUP_FAILED, "대상 OA가 행정 이력에 없음"
        )
    if len(positions) > 1:
        return Missing("admin_history", UnverifiedReason.AMBIGUOUS, "대상 OA가 행정 이력에 두 번")
    kept = admin[: positions[0] + 1]
    # 두 표의 번호는 한쪽에만 하이픈이 있을 수 있어 같은 꼴로 맞춰 본다
    numbers = {_receipt(r.number) for r in kept}
    kept_claims = [c for c in claims or [] if _receipt(c.receipt_number) in numbers]
    if claims is not None and len(kept_claims) < len(claims):
        logger.info(
            "cut_at_oa: OA 뒤(또는 이력에 없는) 청구항 변경 %d줄을 뺌",
            len(claims) - len(kept_claims),
        )
    receipts = {_receipt(c.receipt_number) for c in kept_claims} if claims is not None else None
    history = [HistoryEvent(kind=_kind(r, receipts), doc_number_text=r.number) for r in kept]
    return CaseAtOA(admin=kept, claim_changes=kept_claims, history=history)


@dataclass(frozen=True)
class CaseLookup:
    """조회 한 번의 결과: 자른 이력·청구항 변경·출원서와 못 가져온 것."""

    source: str
    application_number: str
    dispatch_number: str
    cut: CaseAtOA | None  # 이력을 못 가져왔거나 자를 수 없으면 None
    application_document: Path | None
    missing: list[Missing] = field(default_factory=list)


def lookup_case(source: CaseSource, application_number: str, dispatch_number: str) -> CaseLookup:
    """fetch → 파싱 → OA 시점 자르기. 못 가져오거나 못 읽은 것은 missing에 이유와 함께."""
    files = source.fetch(application_number, dispatch_number)
    missing: list[Missing] = []

    claims: list[ClaimChangeRow] | None = None
    if isinstance(files.claim_history, Missing):
        missing.append(files.claim_history)
    else:
        try:
            claims = parse_claim_history(files.claim_history)
        except SourceFormatError as e:
            missing.append(Missing("claim_history", UnverifiedReason.NOT_EXTRACTED, str(e)))

    cut: CaseAtOA | None = None
    if isinstance(files.admin_history, Missing):
        missing.append(files.admin_history)
    else:
        try:
            admin = parse_admin_history(files.admin_history)
        except SourceFormatError as e:
            missing.append(Missing("admin_history", UnverifiedReason.NOT_EXTRACTED, str(e)))
        else:
            result = cut_at_oa(admin, claims, dispatch_number)
            if isinstance(result, Missing):
                missing.append(result)
            else:
                cut = result

    document = None
    if isinstance(files.application_document, Missing):
        missing.append(files.application_document)
    else:
        document = files.application_document
    for m in missing:
        logger.warning(
            "사건 조회(%s): %s 없음 (%s: %s)", source.name, m.what, m.reason.value, m.detail
        )
    return CaseLookup(source.name, application_number, dispatch_number, cut, document, missing)
