"""사건 자료 묶기 규칙 (#16): 번호 읽기·정규화, 같은 사건·같은 문서로 묶기, 심사 대상 판, 빠진 자료.

기준은 docs/features/F1/design.md 4절과 requirements 합격 기준 4·8.
출원번호 + 발송번호(OA) / 접수번호(보정서)로 묶고, 날짜만으로 합치지 않는다.
OA 시점 자르기는 여기서 하지 않는다 (고정 단계 cut_to_oa, #54).
"""

import logging
import re
from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict

from patent_ai.core.f1_oa_reader.rules import (
    _APP_BODY,
    _DISPATCH_BODY,
    normalize_application_number,
)
from patent_ai.core.schemas.common import (
    ExtractedValue,
    Status,
    StatusValue,
    UnverifiedReason,
    worst_status,
)

logger = logging.getLogger(__name__)

# [가정] 접수번호 꼴: 1-1-YYYY-NNNNNNN-NN (하이픈은 있어도 없어도). 표본 보정서로 확인 (#22).
# 앞뒤에 숫자가 더 붙으면 다른 번호의 일부일 수 있어 인정하지 않는다.
_RECEIPT_BODY = r"(?<!\d)1-?1-?\d{4}-?\d{7}-?\d{2}(?!\d)"

NumberKind = Literal["application", "dispatch", "receipt"]

# 번호 종류 → 꼴. 출원번호·발송번호는 통지서 읽기(rules.py)와 같은 꼴을 쓴다.
_PATTERNS: dict[NumberKind, re.Pattern[str]] = {
    "application": re.compile(_APP_BODY),
    "dispatch": re.compile(_DISPATCH_BODY),
    "receipt": re.compile(_RECEIPT_BODY),
}


def normalize_receipt_number(text: str) -> str | None:
    """글자 속 접수번호를 하이픈 없는 숫자(15자리)로. 꼴이 아니면 None (지어내지 않는다)."""
    m = _PATTERNS["receipt"].search(text)
    return m.group(0).replace("-", "") if m else None


def read_number(kind: NumberKind, text: str | None) -> ExtractedValue[str]:
    """번호 글자 하나를 값으로 읽는다.

    - 꼴이 맞는 번호가 하나면 confirmed, 값은 숫자만, raw_text는 원문 그대로.
    - 꼴이 틀리면 unverified(not_extracted), 값은 비우고 글자는 남긴다 (사람이 보게).
    - 서로 다른 번호가 둘 이상이면 unverified(ambiguous). 하나를 고르지 않는다.
    - 글자가 없으면 unverified(not_extracted), 글자도 없음.
    """
    if text is None or not text.strip():
        return ExtractedValue[str](
            status=Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
        )
    # 글자 전체에서 그 종류 꼴을 모두 찾아 서로 다른 값의 수를 센다
    # (하이픈으로 이어 붙은 번호 둘도 따로 잡힌다)
    values = {m.group(0).replace("-", "") for m in _PATTERNS[kind].finditer(text)}
    if len(values) != 1:
        reason = UnverifiedReason.AMBIGUOUS if values else UnverifiedReason.NOT_EXTRACTED
        return ExtractedValue[str](
            raw_text=text, status=Status(value=StatusValue.UNVERIFIED, reason=reason)
        )
    (value,) = values
    return ExtractedValue[str](
        value=value,
        raw_text=text,
        status=Status(value=StatusValue.CONFIRMED, checked=f"{kind} 번호 꼴 맞음"),
    )


# --- 같은 사건·같은 문서로 묶기 (T2) -------------------------------------------

# 자료 종류. 이력 사건(OA·보정서·의견서)은 문서번호로 열쇠를 만든다.
MaterialKind = Literal["oa", "amendment", "opinion", "claims", "spec", "citation"]
_EVENT_NUMBER: dict[str, NumberKind] = {
    "oa": "dispatch",  # OA는 발송번호
    "amendment": "receipt",  # 보정서는 접수번호
    "opinion": "receipt",  # 의견서는 접수번호
}
# 인용문헌은 다른 출원의 문서라 이 사건 출원번호로 묶지 않는다 (OA와 잇는 것은 빠진 자료 단계)
_NOT_THIS_APPLICATION = {"citation"}


class MaterialInput(BaseModel):
    """묶기에 넣는 자료 한 건. 번호는 읽은 글자 그대로 (정규화 전)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str
    kind: MaterialKind
    source: Literal["uploaded", "api"]
    application_number_text: str | None = None
    doc_number_text: str | None = None  # OA는 발송번호, 보정서·의견서는 접수번호
    date_text: str | None = None  # 보이기용. 묶기에는 쓰지 않는다 (날짜만으로 합치지 않음)


class GroupedMaterial(BaseModel):
    """묶은 자료 한 건. 안 맞는 자료도 빼지 않고 status로 남긴다 (빼는 것은 cut_to_oa)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str
    kind: MaterialKind
    source: Literal["uploaded", "api"]
    application_number: ExtractedValue[str] | None  # 인용문헌은 None (검사 안 함)
    doc_number: ExtractedValue[str] | None  # 이력 사건만
    key: str | None  # 예: "oa:952099012345678". confirmed인 이력 사건만
    status: Status


def _conflict() -> Status:
    return Status(value=StatusValue.CONFLICT)


def _group_one(m: MaterialInput, case_application_number: str) -> GroupedMaterial:
    """자료 한 건의 번호를 읽고 상태·열쇠를 정한다."""
    if m.kind in _NOT_THIS_APPLICATION:
        return GroupedMaterial(
            **m.model_dump(include={"document_id", "kind", "source"}),
            application_number=None,
            doc_number=None,
            key=None,
            status=Status(value=StatusValue.CONFIRMED, checked="인용문헌: 출원번호로 묶지 않음"),
        )

    app = read_number("application", m.application_number_text)
    statuses = [app.status]
    # 출원번호를 읽었는데 사건과 다르면 충돌 (다른 사건 자료가 섞임)
    if app.value is not None and app.value != case_application_number:
        statuses.insert(0, _conflict())

    doc = None
    if m.kind in _EVENT_NUMBER:
        doc = read_number(_EVENT_NUMBER[m.kind], m.doc_number_text)
        statuses.append(doc.status)

    status = worst_status(statuses, checked_summary="출원번호·문서번호 확인")
    key = None
    if status.value == StatusValue.CONFIRMED and doc is not None:
        key = f"{m.kind}:{doc.value}"
    return GroupedMaterial(
        **m.model_dump(include={"document_id", "kind", "source"}),
        application_number=app,
        doc_number=doc,
        key=key,
        status=status,
    )


def group_materials(
    materials: list[MaterialInput], case_application_number: str
) -> list[GroupedMaterial]:
    """사건 자료를 출원번호 + 발송번호(OA) / 접수번호(보정서·의견서)로 묶는다.

    - 같은 열쇠 = 같은 문서 (예: 자동 조회 OA와 올린 OA).
    - 출원번호가 다르면 conflict, 번호를 못 읽으면 unverified. 둘 다 열쇠 없음.
    - 같은 접수번호인데 종류가 다르면(보정서 vs 의견서) 둘 다 conflict.
    - 날짜는 보지 않는다.

    case_application_number는 하이픈이 있어도 숫자로 맞춘다. 출원번호 꼴이 아니면 ValueError
    (사건 번호를 모르면 묶을 수 없으니 부르는 쪽이 먼저 출원번호를 확인해야 한다).
    """
    case_number = normalize_application_number(case_application_number)
    if case_number is None:
        raise ValueError(f"사건 출원번호 꼴이 아님: {case_application_number!r}")
    if not materials:
        logger.warning("group_materials: 묶을 자료가 없음 (빈 목록)")
        return []
    grouped = [_group_one(m, case_number) for m in materials]

    # 같은 문서번호에 종류가 둘 이상이면 어느 쪽이 맞는지 모르니 둘 다 충돌로 바꾼다
    kinds_by_number: dict[str, set[str]] = defaultdict(set)
    for g in grouped:
        if g.key is not None and g.doc_number is not None:
            kinds_by_number[g.doc_number.value].add(g.kind)
    clashed = {n for n, kinds in kinds_by_number.items() if len(kinds) > 1}
    return [
        g.model_copy(update={"key": None, "status": _conflict()})
        if g.key is not None and g.doc_number is not None and g.doc_number.value in clashed
        else g
        for g in grouped
    ]
