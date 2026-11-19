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
from patent_ai.core.schemas.case_materials import (
    CaseDocument,
    CaseMaterials,
    HeldTask,
    LookupResult,
    MissingMaterial,
)
from patent_ai.core.schemas.common import (
    ExtractedValue,
    Status,
    StatusValue,
    UnverifiedReason,
    worst_status,
)
from patent_ai.core.schemas.oa_result import Citation, OAResult
from patent_ai.core.schemas.propagation import collect_review_items

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


def _unverified(reason: UnverifiedReason, raw_text: str | None = None) -> ExtractedValue[str]:
    """확인되지 않은 값 (값 없음, 원문 글자는 있으면 남김)."""
    return ExtractedValue[str](
        raw_text=raw_text, status=Status(value=StatusValue.UNVERIFIED, reason=reason)
    )


def read_number(kind: NumberKind, text: str | None) -> ExtractedValue[str]:
    """번호 글자 하나를 값으로 읽는다.

    - 꼴이 맞는 번호가 하나면 confirmed, 값은 숫자만, raw_text는 원문 그대로.
    - 꼴이 틀리면 unverified(not_extracted), 값은 비우고 글자는 남긴다 (사람이 보게).
    - 서로 다른 번호가 둘 이상이면 unverified(ambiguous). 하나를 고르지 않는다.
    - 글자가 없으면 unverified(not_extracted), 글자도 없음.
    """
    if text is None or not text.strip():
        return _unverified(UnverifiedReason.NOT_EXTRACTED)
    # 글자 전체에서 그 종류 꼴을 모두 찾아 서로 다른 값의 수를 센다
    # (하이픈으로 이어 붙은 번호 둘도 따로 잡힌다)
    values = {m.group(0).replace("-", "") for m in _PATTERNS[kind].finditer(text)}
    if len(values) != 1:
        reason = UnverifiedReason.AMBIGUOUS if values else UnverifiedReason.NOT_EXTRACTED
        return _unverified(reason, text)
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


# --- 심사 대상 판 고르기 (T3) ---------------------------------------------------

V0 = "v0"  # [가정] 출원 때 판 이름 (보정서 없음). 판 이름 규칙은 저장 PR(#55 뒤)에서 맞춘다


class HistoryEvent(BaseModel):
    """행정 이력 사건 하나. 목록 순서가 곧 이력 순서다 (순서는 #54 조회가 정한다)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["oa", "amendment", "opinion", "other"]
    doc_number_text: str | None = None  # OA는 발송번호, 보정서·의견서는 접수번호 (원문 글자)


def select_examined_version(
    history: list[HistoryEvent] | None, target_dispatch: str | None
) -> ExtractedValue[str]:
    """대상 OA(발송번호)가 심사한 청구항 판을 고른다 (design.md 4절).

    - 이력 순서에서 대상 OA **앞**의 마지막 보정서 접수번호가 그 판. 보정서가 없으면 "v0".
    - 의견서는 판을 만들지 않으니 건너뛴다. 날짜는 보지 않는다.
    - 이력이 없거나 비었거나 대상 OA가 이력에 없으면 unverified(lookup_failed).
      단 번호를 못 읽은 OA가 이력에 있으면 unverified(not_extracted).
    - 대상 OA가 이력에 두 번 나오면 unverified(ambiguous).
    - 대상 발송번호를 못 읽으면 unverified(input_unverified).
    - 마지막 보정서 번호를 못 읽으면 unverified(그 번호의 이유) (그 판을 모름).
    """
    target = read_number("dispatch", target_dispatch).value
    if target is None:
        return _unverified(UnverifiedReason.INPUT_UNVERIFIED, target_dispatch)
    if history is None:
        return _unverified(UnverifiedReason.LOOKUP_FAILED)
    if not history:
        logger.warning("select_examined_version: 이력이 비어 있음 -> unverified(lookup_failed)")
        return _unverified(UnverifiedReason.LOOKUP_FAILED)

    # 대상 OA가 이력 몇 번째에 있는지 찾는다 (번호로만 찾는다)
    positions = [
        i
        for i, e in enumerate(history)
        if e.kind == "oa" and read_number("dispatch", e.doc_number_text).value == target
    ]
    if not positions:
        # 번호를 못 읽은 OA가 있으면 그게 대상일 수도 있다: 조회 실패와 구분한다
        unreadable = any(
            e.kind == "oa" and read_number("dispatch", e.doc_number_text).value is None
            for e in history
        )
        reason = UnverifiedReason.NOT_EXTRACTED if unreadable else UnverifiedReason.LOOKUP_FAILED
        return _unverified(reason)
    if len(positions) > 1:
        return _unverified(UnverifiedReason.AMBIGUOUS)

    # 대상 OA 앞에서 가장 늦은 보정서 = 심사 대상 판을 만든 보정서
    before = [e for e in history[: positions[0]] if e.kind == "amendment"]
    if not before:
        return ExtractedValue[str](
            value=V0,
            status=Status(
                value=StatusValue.CONFIRMED, checked="대상 OA 앞 보정서 없음: 출원 때 판"
            ),
        )
    last = read_number("receipt", before[-1].doc_number_text)
    if last.value is None:
        # 못 읽은 이유(not_extracted / ambiguous)를 그대로 넘긴다
        return _unverified(last.status.reason, before[-1].doc_number_text)
    return ExtractedValue[str](
        value=last.value,
        raw_text=last.raw_text,
        status=Status(value=StatusValue.CONFIRMED, checked="대상 OA 앞 마지막 보정서 접수번호"),
    )


# --- 빠진 자료 → CaseMaterials (T4) ---------------------------------------------


def _citation_name(c: Citation) -> str:
    """사람이 읽는 인용문헌 이름: 라벨 + 번호 값(없으면 원문 글자)."""
    return f"{c.label} {c.number.value or c.number.raw_text or '번호 모름'}"


def _oa_citations(oa: OAResult) -> list[Citation]:
    """OA의 인용문헌을 라벨 기준으로 한 번씩 (같은 문헌은 같은 라벨)."""
    seen: dict[str, Citation] = {}
    for rej in oa.rejections:
        for c in rej.citations:
            seen.setdefault(c.label, c)
    return list(seen.values())


def _missing_reason(
    c: Citation, received_citations: set[str], lookup_failures: dict[str, LookupResult]
) -> LookupResult | None:
    """인용문헌이 빠졌으면 그 이유, 있으면 None."""
    if c.country.value is not None and not c.country_supported:
        return LookupResult.UNSUPPORTED_COUNTRY  # 지원 안 하는 나라: 직접 확인
    key = c.number.value
    if key is None:
        return LookupResult.LOOKUP_FAILED  # 번호를 못 읽어 조회할 수 없음
    if key in received_citations:
        return None
    # 조회 쪽(#54)이 이유를 주면 그 이유, 없으면 못 가져온 것으로 본다
    return lookup_failures.get(key, LookupResult.LOOKUP_FAILED)


def build_case_materials(
    case_id: str,
    grouped: list[GroupedMaterial],
    oa: OAResult,
    received_citations: set[str],
    lookup_failures: dict[str, LookupResult] | None = None,
) -> CaseMaterials:
    """묶은 자료와 OA 인용문헌으로 사건 자료·빠진 자료·보류 작업을 채운다 (합격 기준 4).

    - received_citations: 본문을 받은 인용문헌 번호(키 꼴). lookup_failures: 못 받은 번호 → 이유.
    - 빠진 인용문헌마다 missing 한 줄 + 그 인용문헌의 F3 대비만 held_tasks. 나머지는 진행.
    - 지원 안 하는 나라는 ask_upload=False ("직접 확인"), 그 밖은 "올려 주세요".
    - documents: 같은 열쇠(같은 문서)는 하나만, 올린 것 우선. 나머지는 경고 로그.
      confirmed가 아닌 자료(다른 출원번호·번호 못 읽음)도 빼지 않는다 (빼는 것은 cut_to_oa).
    - review_items_count = 검토할 사항 모으기(collect_review_items) 줄 수
      + confirmed가 아닌 자료 수 (조용히 섞이지 않게).
    """
    lookup_failures = lookup_failures or {}
    citations = _oa_citations(oa)
    if not citations:
        logger.warning("build_case_materials: OA 인용문헌이 0건 (빠진 자료 검사 없음)")

    missing: list[MissingMaterial] = []
    held: list[HeldTask] = []
    for c in citations:
        reason = _missing_reason(c, received_citations, lookup_failures)
        if reason is None:
            continue
        what = f"{_citation_name(c)} 본문"
        task = f"F3 대비: {_citation_name(c)}"
        missing.append(
            MissingMaterial(
                what=what,
                depends_on_tasks=[task],
                lookup_result=reason,
                ask_upload=reason != LookupResult.UNSUPPORTED_COUNTRY,
            )
        )
        held.append(HeldTask(task=task, waiting_for=what))

    materials = CaseMaterials(
        case_id=case_id,
        documents=[
            CaseDocument(document_id=g.document_id, kind=g.kind, source=g.source)
            for g in _one_per_key(grouped)
        ],
        missing=missing,
        held_tasks=held,
    )
    # 묶기에서 확인되지 않은 자료도 사람이 보게 검토할 사항 수에 더한다
    unsettled = sum(1 for g in grouped if g.status.value != StatusValue.CONFIRMED)
    count = len(collect_review_items([oa], materials)) + unsettled
    return materials.model_copy(update={"review_items_count": count})


def _one_per_key(grouped: list[GroupedMaterial]) -> list[GroupedMaterial]:
    """같은 열쇠(같은 문서)는 하나만 남긴다. 사용자가 올린 것을 우선, 그다음 앞에 온 것.

    열쇠가 없는 자료(인용문헌·청구항·확인 안 된 자료)는 모두 남긴다. 순서는 처음 순서 그대로.
    """
    chosen: dict[str, GroupedMaterial] = {}
    for g in grouped:
        if g.key is None:
            continue
        kept = chosen.get(g.key)
        if kept is None or (kept.source != "uploaded" and g.source == "uploaded"):
            chosen[g.key] = g
    out = []
    for g in grouped:
        if g.key is None or chosen[g.key] is g:
            out.append(g)
        else:
            logger.warning(
                "build_case_materials: 같은 문서(%s)가 또 있어 %s 대신 %s를 씀",
                g.key,
                g.document_id,
                chosen[g.key].document_id,
            )
    return out
