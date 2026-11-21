"""사건 저장소 (#16 T6): 묶기 결과를 저장하고 다시 읽는다. 인터페이스·표 줄 계산·메모리 fake.

- 표에 넣을 줄은 `plan_case_rows` 한 곳에서 계산한다. 메모리 fake와 Postgres 구현
  (`case_repository_pg.py`)이 같은 줄을 쓰니 둘의 저장 규칙이 어긋나지 않는다.
- 두 곳에 있는 값은 한 곳에서 채운다 (#120 리뷰 고칠 것 1번):
  보정서 판 접수번호(`claim_versions.source_doc_number`)는 그 판의 이력 줄(`case_events.doc_number`)
  에서, 세 표(`oas`·`documents`·`claim_versions`)의 `case_id`는 잇는 이력 줄의 `case_id`에서
  (이력 줄이 없으면 저장하는 사건에서) 가져온다.
- 청구항 판은 종류(`source_kind`)를 꼭 정한다. AI 입력은 출원·보정 판만 (#123 리뷰 고칠 것 2번).
- 부르는 방향은 core → db (ADR 0003). db는 core를 모른다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, model_validator

from patent_ai.core.f1_oa_reader.case_grouping import (
    AS_FILED_VERSION,
    GroupedMaterial,
    HistoryEvent,
    MaterialInput,
    answer_missing,
    group_materials,
    read_number,
    select_examined_version,
)
from patent_ai.core.schemas.case_materials import CaseMaterials
from patent_ai.core.schemas.common import ExtractedValue, Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.oa_result import OAResult
from patent_ai.db.ids import new_id

logger = logging.getLogger(__name__)

# 청구항 판 종류. DB claim_versions.source_kind CHECK 값과 같다
SourceKind = Literal["application", "amendment", "publication", "registration"]
# AI 입력으로 쓰는 판. 공개·등록공보 판은 채점 확인용이라 AI에 넣지 않는다
AI_INPUT_KINDS: frozenset[str] = frozenset({"application", "amendment"})
# 청구항이 든 문서 종류. 저장할 때 판 종류를 꼭 받아야 한다
_CLAIM_DOCUMENT_KINDS = {"claims", "spec"}
# 이력 종류별 문서번호 꼴 (OA는 발송번호, 보정서·의견서는 접수번호)
_NUMBER_KIND = {"oa": "dispatch", "amendment": "receipt", "opinion": "receipt"}
# M1은 로그인이 없어 기본 사용자 한 명 (마이그레이션이 넣음)
DEFAULT_USER_ID = "u_default"


class CaseStoreError(ValueError):
    """저장할 수 없는 묶기 결과 (판 종류 없음, 잇는 이력 없음, 같은 사건 두 번 등)."""


class DuplicateDocumentError(CaseStoreError):
    """같은 사건에 같은 파일(sha256)이 두 번. API는 409로 돌려준다 (T7)."""


class UnknownCaseError(CaseStoreError):
    """저장된 사건(묶기 결과)이 없음. API는 404로 돌려준다 (T7)."""


# --- 저장할 입력 ------------------------------------------------------------------


class StoredFile(BaseModel):
    """자료 한 건의 파일 정보. 원본은 디스크, DB에는 경로·해시만."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    sha256: str
    received_at: datetime


class ClaimVersionInput(BaseModel):
    """청구항 문서(claims·spec) 하나가 어느 판인지. 판 종류는 빠뜨릴 수 없다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str
    source_kind: SourceKind
    receipt_number_text: str | None = None  # 보정서 판: 그 보정서 접수번호 (원문 글자)
    source_doc_number: str | None = None  # 공보 판: 공개·등록번호


class CaseRecord(BaseModel):
    """저장할 사건 하나: 묶은 자료 + 파일 + 이력 + 청구항 판 + 사건 자료(빠진 자료 포함)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    application_number: str  # 하이픈 있어도 됨. 저장은 숫자만
    grouped: list[GroupedMaterial]
    files: dict[str, StoredFile]  # document_id → 파일
    history: list[HistoryEvent]  # 순서 = 행정 이력 순서
    claim_versions: list[ClaimVersionInput]
    materials: CaseMaterials

    @model_validator(mode="after")
    def _사건_id가_같음(self) -> CaseRecord:
        if self.materials.case_id != self.case_id:
            raise ValueError("materials.case_id가 case_id와 다름")
        return self


# --- 표 줄 (db/models/cases.py 칸과 같은 이름) --------------------------------------


@dataclass(frozen=True)
class CaseRow:
    id: str
    application_number: str
    user_id: str = DEFAULT_USER_ID


@dataclass(frozen=True)
class EventRow:
    id: str
    case_id: str
    kind: str
    doc_number: str | None
    seq: int | None  # 이력 순서 (1부터). 이력에 없고 자료로만 온 사건은 None


@dataclass(frozen=True)
class DocumentRow:
    id: str
    case_id: str
    case_event_id: str | None
    kind: str
    path: str
    sha256: str
    source: str
    received_at: datetime


@dataclass(frozen=True)
class ClaimVersionRow:
    id: str
    case_id: str
    version: int  # 0 = 출원 때 판
    source_kind: str
    source_doc_number: str | None
    case_event_id: str | None
    document_id: str | None


@dataclass(frozen=True)
class OARow:
    id: str
    case_id: str
    case_event_id: str
    examined_claim_version_id: str | None  # 모르면 비움 → 읽을 때 unverified
    document_id: str | None


@dataclass(frozen=True)
class OAResultRowData:
    id: str
    oa_id: str
    run_id: str
    body: dict[str, Any]
    status: str
    origin: str


@dataclass(frozen=True)
class OAVersionRow:
    """사건 보기(GET /cases/{id})의 OA별 심사 대상 판 한 줄."""

    oa_id: str
    dispatch_number: str | None
    examined_claim_version: ExtractedValue[str]


@dataclass(frozen=True)
class CaseRows:
    """사건 하나를 저장할 표 줄 전부. 넣는 순서도 이 순서 (외래 키 순서)."""

    case: CaseRow
    events: list[EventRow] = field(default_factory=list)
    documents: list[DocumentRow] = field(default_factory=list)
    claim_versions: list[ClaimVersionRow] = field(default_factory=list)
    oas: list[OARow] = field(default_factory=list)
    materials_body: dict[str, Any] = field(default_factory=dict)


# --- 표 줄 계산 (메모리·Postgres 공통) ----------------------------------------------


def _event_number(kind: str, text: str | None) -> str | None:
    """이력 줄의 문서번호 (숫자만). 꼴을 모르는 종류나 못 읽은 번호는 None."""
    number_kind = _NUMBER_KIND.get(kind)
    return read_number(number_kind, text).value if number_kind else None


def _plan_events(record: CaseRecord, case_id: str) -> list[EventRow]:
    """이력 줄 + 이력에는 없고 자료로만 온 사건 줄 (seq 없음)."""
    rows: list[EventRow] = []
    seen: set[tuple[str, str]] = set()
    for seq, e in enumerate(record.history, start=1):
        number = _event_number(e.kind, e.doc_number_text)
        if number is not None:
            if (e.kind, number) in seen:
                # DB unique(case_id, kind, doc_number)에 걸린다. 어느 줄이 맞는지 모르니 거부
                raise CaseStoreError(f"이력에 같은 {e.kind} 번호가 두 번: {number}")
            seen.add((e.kind, number))
        rows.append(EventRow(new_id("ev"), case_id, e.kind, number, seq))
    for g in record.grouped:
        if g.key is None or g.doc_number is None:
            continue
        if (g.kind, g.doc_number.value) not in seen:
            seen.add((g.kind, g.doc_number.value))
            rows.append(EventRow(new_id("ev"), case_id, g.kind, g.doc_number.value, None))
    return rows


def _plan_documents(record: CaseRecord, case_id: str, events: list[EventRow]) -> list[DocumentRow]:
    by_key = {(e.kind, e.doc_number): e for e in events if e.doc_number is not None}
    rows: list[DocumentRow] = []
    seen_sha: dict[str, str] = {}
    for g in record.grouped:
        f = record.files.get(g.document_id)
        if f is None:
            raise CaseStoreError(f"파일 정보가 없는 자료: {g.document_id}")
        if f.sha256 in seen_sha:
            raise DuplicateDocumentError(
                f"같은 파일이 두 번: {seen_sha[f.sha256]}, {g.document_id}"
            )
        seen_sha[f.sha256] = g.document_id
        event = None
        if g.key is not None and g.doc_number is not None:
            event = by_key[(g.kind, g.doc_number.value)]
        rows.append(
            DocumentRow(
                id=g.document_id,
                # 이력 줄에 이어지면 그 줄의 사건, 아니면(인용문헌·청구항) 저장하는 사건
                case_id=event.case_id if event else case_id,
                case_event_id=event.id if event else None,
                kind=g.kind,
                path=f.path,
                sha256=f.sha256,
                source=g.source,
                received_at=f.received_at,
            )
        )
    return rows


def _plan_claim_versions(
    record: CaseRecord, case_id: str, events: list[EventRow], documents: list[DocumentRow]
) -> list[ClaimVersionRow]:
    """청구항 판: 0 = 출원 때 판(늘 하나), 그다음 보정서 판(이력 순서), 그다음 공보 판."""
    # 판이 가리키는 문서는 이 사건 자료 중 청구항 문서여야 하고, 문서 하나에 판 하나.
    # (없는 문서면 메모리 fake는 들어가고 Postgres는 외래 키에서 깨져 둘이 달라진다)
    kinds_by_doc = {d.id: d.kind for d in documents}
    inputs_by_doc: dict[str, ClaimVersionInput] = {}
    for c in record.claim_versions:
        if c.document_id not in kinds_by_doc:
            raise CaseStoreError(f"청구항 판이 가리키는 문서 {c.document_id}가 저장할 자료에 없음")
        if kinds_by_doc[c.document_id] not in _CLAIM_DOCUMENT_KINDS:
            raise CaseStoreError(
                f"청구항 판이 청구항 문서가 아닌 {c.document_id}"
                f"({kinds_by_doc[c.document_id]})를 가리킴"
            )
        if c.document_id in inputs_by_doc:
            raise CaseStoreError(f"청구항 문서 {c.document_id}에 판이 둘")
        inputs_by_doc[c.document_id] = c
    # 청구항 문서는 판 종류를 꼭 받는다 (등록공보 청구항이 출원 판처럼 섞이지 않게)
    for d in documents:
        if d.kind in _CLAIM_DOCUMENT_KINDS and d.id not in inputs_by_doc:
            raise CaseStoreError(f"청구항 문서 {d.id}의 판 종류(source_kind)가 없음")

    apps = [c for c in record.claim_versions if c.source_kind == "application"]
    if len(apps) > 1:
        raise CaseStoreError("출원 때 판 문서가 둘 이상")
    rows = [
        ClaimVersionRow(
            new_id("cv"), case_id, 0, "application", None, None,
            apps[0].document_id if apps else None,
        )
    ]  # fmt: skip

    # 보정서 판: 각하되지 않은 보정서 이력 줄마다 하나. 번호는 그 줄에서 가져온다
    dismissed = {
        _event_number("amendment", e.doc_number_text)
        for e in record.history
        if e.kind == "amendment" and e.dismissed
    }
    amendment_docs = {
        d.case_event_id: d.id for d in documents if d.kind == "amendment" and d.case_event_id
    }
    by_event: dict[str, ClaimVersionRow] = {}
    ordered = sorted(
        (e for e in events if e.kind == "amendment" and e.doc_number is not None),
        key=lambda e: (e.seq is None, e.seq or 0),
    )
    for e in ordered:
        if e.doc_number in dismissed:
            continue  # 보정각하: 판을 만들지 않는다 (특허법 제51조)
        row = ClaimVersionRow(
            id=new_id("cv"),
            case_id=e.case_id,  # 잇는 이력 줄의 사건
            version=len(rows),
            source_kind="amendment",
            source_doc_number=e.doc_number,  # 잇는 이력 줄의 접수번호
            case_event_id=e.id,
            document_id=amendment_docs.get(e.id),
        )
        by_event[e.id] = row
        rows.append(row)

    amendment_events = {e.doc_number: e for e in ordered}
    for c in record.claim_versions:
        if c.source_kind == "amendment":
            # 따로 올린 보정 청구항: 그 보정서 이력 줄이 있어야 한다 (없으면 저장 거부)
            receipt = read_number("receipt", c.receipt_number_text).value
            event = amendment_events.get(receipt) if receipt else None
            if event is None or event.id not in by_event:
                raise CaseStoreError(f"보정서 판 {c.document_id}에 잇는 보정서 이력이 없음")
            row = by_event[event.id]
            if row.document_id is not None:
                raise CaseStoreError(f"보정서 판 {receipt}에 문서가 둘")
            rows[rows.index(row)] = by_event[event.id] = replace(row, document_id=c.document_id)
        elif c.source_kind in ("publication", "registration"):
            rows.append(
                ClaimVersionRow(
                    new_id("cv"), case_id, len(rows), c.source_kind,
                    c.source_doc_number, None, c.document_id,
                )
            )  # fmt: skip
    return rows


def _plan_oas(
    record: CaseRecord,
    events: list[EventRow],
    documents: list[DocumentRow],
    versions: list[ClaimVersionRow],
) -> list[OARow]:
    """OA 이력 줄마다 OA 하나. 심사 대상 판은 T5 규칙(select_examined_version)으로 고른다."""
    # 같은 OA 문서가 여럿이면(자동 조회 + 올림) 사건 자료에 남은 것(올린 것 우선)을 잇는다
    kept = {d.document_id for d in record.materials.documents}
    docs_by_event: dict[str, str] = {}
    for d in documents:
        if d.kind == "oa" and d.case_event_id and (d.case_event_id not in docs_by_event):
            if d.id in kept:
                docs_by_event[d.case_event_id] = d.id
    v0 = versions[0]
    by_receipt = {v.source_doc_number: v for v in versions if v.source_kind == "amendment"}
    rows = []
    for e in events:
        if e.kind != "oa" or e.doc_number is None:
            continue
        examined = select_examined_version(record.history, e.doc_number)
        version = None
        if examined.status.value == StatusValue.CONFIRMED:
            version = v0 if examined.value == AS_FILED_VERSION else by_receipt.get(examined.value)
        rows.append(
            OARow(
                id=new_id("oa"),
                case_id=e.case_id,  # 잇는 이력 줄의 사건
                case_event_id=e.id,
                examined_claim_version_id=version.id if version else None,
                document_id=docs_by_event.get(e.id),
            )
        )
    return rows


def plan_case_rows(record: CaseRecord) -> CaseRows:
    """묶기 결과 → 표 줄. 저장할 수 없으면 CaseStoreError (DB에 닿기 전에 막는다)."""
    case_number = read_number("application", record.application_number).value
    if case_number is None:
        raise CaseStoreError(f"사건 출원번호 꼴이 아님: {record.application_number!r}")
    case = CaseRow(id=record.case_id, application_number=case_number)
    events = _plan_events(record, case.id)
    documents = _plan_documents(record, case.id, events)
    versions = _plan_claim_versions(record, case.id, events, documents)
    oas = _plan_oas(record, events, documents, versions)
    if not record.grouped:
        logger.warning("plan_case_rows: 저장할 자료가 0건 (사건 %s)", record.case_id)
    return CaseRows(
        case=case,
        events=events,
        documents=documents,
        claim_versions=versions,
        oas=oas,
        materials_body=record.materials.model_dump(mode="json"),
    )


def oa_result_row(oa_id: str, run_id: str, result: OAResult) -> OAResultRowData:
    """OA 결과 한 줄. 거르는 칸 status·origin은 본문(모델) 값에서만 뽑는다 (#120 리뷰 5번)."""
    return OAResultRowData(
        id=new_id("res"),
        oa_id=oa_id,
        run_id=run_id,
        body=result.model_dump(mode="json"),
        status=result.status.value.value,
        origin=result.origin.value,
    )


def examined_from_version(version: ClaimVersionRow | None) -> ExtractedValue[str]:
    """저장된 심사 대상 판 → OAResult.examined_claim_version 값 (T5와 같은 모양)."""
    if version is None:
        return ExtractedValue[str](
            status=Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.LOOKUP_FAILED)
        )
    if version.source_kind == "application":
        return ExtractedValue[str](
            value=AS_FILED_VERSION,
            status=Status(value=StatusValue.CONFIRMED, checked="저장된 심사 대상 판: 출원 때 판"),
        )
    return ExtractedValue[str](
        value=version.source_doc_number,
        status=Status(value=StatusValue.CONFIRMED, checked="저장된 심사 대상 판: 보정서 접수번호"),
    )


def uploaded_document_row(case_id: str, document: GroupedMaterial, file: StoredFile) -> DocumentRow:
    """올린 자료 한 건의 문서 줄. 인용문헌은 이력 줄에 잇지 않고 그 사건에 둔다."""
    if document.key is not None:
        # 이력 줄(OA·보정서)에 잇는 자료는 이 길로 더하지 않는다 (판·OA 줄도 다시 계산해야 함)
        raise CaseStoreError(f"이력 줄에 잇는 자료는 더할 수 없음: {document.document_id}")
    return DocumentRow(
        id=document.document_id,
        case_id=case_id,
        case_event_id=None,
        kind=document.kind,
        path=file.path,
        sha256=file.sha256,
        source=document.source,
        received_at=file.received_at,
    )


def sorted_events(events: list[EventRow]) -> list[EventRow]:
    """이력 순서(seq)대로, seq 없는 줄은 뒤에 (뒤쪽 줄끼리 순서는 정하지 않는다)."""
    return sorted(events, key=lambda e: (e.seq is None, e.seq or 0))


def upload_missing_material(
    repo: CaseRepository,
    case_id: str,
    what: str,
    file: StoredFile,
    document_id: str | None = None,
) -> CaseMaterials:
    """빠진 자료 `what`에 올린 파일로 답한다: 묶기 → 사건 자료 고치기 → 저장 (T7).

    지금 빠진 자료는 인용문헌 본문만 만든다 (build_case_materials). 그래서 올린 자료 종류는
    citation으로 둔다. 커밋은 부르는 쪽(API)이 한다.
    """
    application_number = repo.case_application_number(case_id)
    materials = repo.load_case_materials(case_id)
    if application_number is None or materials is None:
        raise UnknownCaseError(f"저장된 사건이 없음: {case_id}")
    material = MaterialInput(
        document_id=document_id or new_id("doc"), kind="citation", source="uploaded"
    )
    (grouped,) = group_materials([material], application_number)
    updated = answer_missing(materials, what, grouped)
    repo.add_document(case_id, grouped, file, updated)
    return updated


# --- 저장소 인터페이스와 메모리 fake -----------------------------------------------


class CaseRepository(Protocol):
    """사건 저장소. 메모리 fake와 Postgres 구현이 같은 결과를 낸다."""

    def save_case(self, record: CaseRecord) -> None:
        """새 사건 저장. 같은 사건이 이미 있으면 CaseStoreError, 같은 파일 두 번이면 중복 오류."""
        ...

    def load_case_materials(self, case_id: str) -> CaseMaterials | None:
        """사건 자료. 없는 사건이면 None (API는 404)."""
        ...

    def case_application_number(self, case_id: str) -> str | None:
        """저장된 사건의 출원번호(숫자만). 없는 사건이면 None."""
        ...

    def add_document(
        self, case_id: str, document: GroupedMaterial, file: StoredFile, materials: CaseMaterials
    ) -> None:
        """이미 저장된 사건에 자료 한 건을 더하고 사건 자료를 새 값으로 바꾼다 (T7 올리기).

        없는 사건은 UnknownCaseError, 같은 사건에 같은 파일이면 DuplicateDocumentError.
        """
        ...

    def events(self, case_id: str) -> list[EventRow]:
        """사건 이력 줄. 이력 순서(seq)대로, 자료로만 온 줄(seq 없음)은 뒤에."""
        ...

    def oa_versions(self, case_id: str) -> list[OAVersionRow]:
        """OA마다 심사 대상 판 (이력 순서대로)."""
        ...

    def claim_versions(self, case_id: str) -> list[ClaimVersionRow]: ...

    def ai_input_claim_versions(self, case_id: str) -> list[ClaimVersionRow]:
        """AI 입력으로 쓸 판만 (출원·보정). 공개·등록공보 판은 뺀다."""
        ...

    def examined_claim_version(self, case_id: str, dispatch_number: str) -> ExtractedValue[str]:
        """그 OA의 심사 대상 판. 모르면 unverified(lookup_failed)."""
        ...

    def save_oa_result(
        self, case_id: str, dispatch_number: str, run_id: str, result: OAResult
    ) -> str:
        """OA 결과 저장 (앞 결과는 지우지 않음). 돌려주는 것은 결과 id."""
        ...

    def load_oa_result(self, case_id: str, dispatch_number: str) -> OAResult | None:
        """그 OA의 가장 최근 결과. 없으면 None."""
        ...


class InMemoryCaseRepository:
    """테스트·API 테스트용 메모리 저장소. 표 줄은 plan_case_rows가 만든 것 그대로."""

    def __init__(self) -> None:
        self._cases: dict[str, CaseRows] = {}
        self._results: list[OAResultRowData] = []

    def save_case(self, record: CaseRecord) -> None:
        rows = plan_case_rows(record)
        numbers = {r.case.application_number for r in self._cases.values()}
        if record.case_id in self._cases or rows.case.application_number in numbers:
            raise CaseStoreError(f"이미 있는 사건: {record.case_id}")
        self._cases[record.case_id] = rows

    def load_case_materials(self, case_id: str) -> CaseMaterials | None:
        rows = self._cases.get(case_id)
        return CaseMaterials.model_validate(rows.materials_body) if rows else None

    def case_application_number(self, case_id: str) -> str | None:
        rows = self._cases.get(case_id)
        return rows.case.application_number if rows else None

    def add_document(
        self, case_id: str, document: GroupedMaterial, file: StoredFile, materials: CaseMaterials
    ) -> None:
        rows = self._cases.get(case_id)
        if rows is None:
            raise UnknownCaseError(f"저장된 사건이 없음: {case_id}")
        if any(d.sha256 == file.sha256 for d in rows.documents):
            raise DuplicateDocumentError("같은 사건에 같은 파일이 이미 있음")
        doc = uploaded_document_row(case_id, document, file)
        self._cases[case_id] = replace(
            rows,
            documents=[*rows.documents, doc],
            materials_body=materials.model_dump(mode="json"),
        )

    def events(self, case_id: str) -> list[EventRow]:
        rows = self._cases.get(case_id)
        return sorted_events(list(rows.events)) if rows else []

    def oa_versions(self, case_id: str) -> list[OAVersionRow]:
        rows = self._cases.get(case_id)
        if rows is None:
            return []
        events = {e.id: e for e in rows.events}
        versions = {v.id: v for v in rows.claim_versions}
        order = {e.id: i for i, e in enumerate(sorted_events(list(rows.events)))}
        return [
            OAVersionRow(
                oa_id=o.id,
                dispatch_number=events[o.case_event_id].doc_number,
                examined_claim_version=examined_from_version(
                    versions.get(o.examined_claim_version_id or "")
                ),
            )
            for o in sorted(rows.oas, key=lambda o: order[o.case_event_id])
        ]

    def claim_versions(self, case_id: str) -> list[ClaimVersionRow]:
        rows = self._cases.get(case_id)
        return list(rows.claim_versions) if rows else []

    def ai_input_claim_versions(self, case_id: str) -> list[ClaimVersionRow]:
        return [v for v in self.claim_versions(case_id) if v.source_kind in AI_INPUT_KINDS]

    def _oa(self, case_id: str, dispatch_number: str) -> OARow | None:
        rows = self._cases.get(case_id)
        number = read_number("dispatch", dispatch_number).value
        if rows is None or number is None:
            return None
        events = {e.id: e for e in rows.events}
        return next((o for o in rows.oas if events[o.case_event_id].doc_number == number), None)

    def examined_claim_version(self, case_id: str, dispatch_number: str) -> ExtractedValue[str]:
        oa = self._oa(case_id, dispatch_number)
        versions = {v.id: v for v in self.claim_versions(case_id)}
        return examined_from_version(versions.get(oa.examined_claim_version_id) if oa else None)

    def save_oa_result(
        self, case_id: str, dispatch_number: str, run_id: str, result: OAResult
    ) -> str:
        oa = self._oa(case_id, dispatch_number)
        if oa is None:
            raise CaseStoreError(f"사건 {case_id}에 OA {dispatch_number}가 없음")
        row = oa_result_row(oa.id, run_id, result)
        self._results.append(row)
        return row.id

    def load_oa_result(self, case_id: str, dispatch_number: str) -> OAResult | None:
        oa = self._oa(case_id, dispatch_number)
        mine = [r for r in self._results if oa is not None and r.oa_id == oa.id]
        return OAResult.model_validate(mine[-1].body) if mine else None
