"""사건 저장소의 Postgres 구현 (#16 T6). 표 줄은 plan_case_rows가 계산한 것 그대로 넣는다.

db/models 표를 쓰고 읽기만 한다 (표 정의는 db/, 저장 규칙은 core/case_repository.py).
트랜잭션 경계(commit)는 부르는 쪽(API)이 정한다. 여기서는 flush까지만.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from patent_ai.core.f1_oa_reader.case_grouping import GroupedMaterial, read_number
from patent_ai.core.f1_oa_reader.case_repository import (
    AI_INPUT_KINDS,
    CaseRecord,
    CaseStoreError,
    ClaimVersionRow,
    DuplicateDocumentError,
    EventRow,
    OAVersionRow,
    StoredFile,
    UnknownCaseError,
    examined_from_version,
    oa_result_row,
    plan_case_rows,
    sorted_events,
    uploaded_document_row,
)
from patent_ai.core.schemas.case_materials import CaseMaterials
from patent_ai.core.schemas.common import ExtractedValue
from patent_ai.core.schemas.oa_result import OAResult
from patent_ai.db.models import (
    OA,
    Case,
    CaseEvent,
    CaseMaterialsRow,
    ClaimVersion,
    Document,
    OAResultRow,
)


def _to_row(v: ClaimVersion) -> ClaimVersionRow:
    return ClaimVersionRow(
        id=v.id,
        case_id=v.case_id,
        version=v.version,
        source_kind=v.source_kind,
        source_doc_number=v.source_doc_number,
        case_event_id=v.case_event_id,
        document_id=v.document_id,
    )


class PostgresCaseRepository:
    def __init__(self, session: Session):
        self._s = session

    def save_case(self, record: CaseRecord) -> None:
        rows = plan_case_rows(record)
        if self._s.get(Case, record.case_id) is not None:
            raise CaseStoreError(f"이미 있는 사건: {record.case_id}")
        # 외래 키 순서대로 넣는다. OA 원문·판 문서를 가리키므로 documents가 판·OA보다 먼저
        groups = [
            [Case(**vars(rows.case))],
            [CaseEvent(**vars(e)) for e in rows.events],
            [Document(**vars(d)) for d in rows.documents],
            [ClaimVersion(**vars(v)) for v in rows.claim_versions],
            [OA(**vars(o)) for o in rows.oas],
            [CaseMaterialsRow(case_id=rows.case.id, body=rows.materials_body)],
        ]
        try:
            with self._s.begin_nested():  # 실패하면 이 사건 줄만 되돌린다
                for group in groups:
                    self._s.add_all(group)
                    self._s.flush()
        except IntegrityError as e:
            name = getattr(getattr(e.orig, "diag", None), "constraint_name", None)
            if name == "uq_documents_case_sha256":
                raise DuplicateDocumentError("같은 사건에 같은 파일이 이미 있음") from e
            if name == "uq_cases_application_number":
                raise CaseStoreError("같은 출원번호 사건이 이미 있음") from e
            raise CaseStoreError(f"저장 실패: {name or e.orig}") from e

    def load_case_materials(self, case_id: str) -> CaseMaterials | None:
        row = self._s.get(CaseMaterialsRow, case_id)
        return CaseMaterials.model_validate(row.body) if row else None

    def case_application_number(self, case_id: str) -> str | None:
        case = self._s.get(Case, case_id)
        return case.application_number if case else None

    def add_document(
        self, case_id: str, document: GroupedMaterial, file: StoredFile, materials: CaseMaterials
    ) -> None:
        row = self._s.get(CaseMaterialsRow, case_id)
        if row is None:
            raise UnknownCaseError(f"저장된 사건이 없음: {case_id}")
        doc = uploaded_document_row(case_id, document, file)
        try:
            with self._s.begin_nested():  # 실패하면 이 문서 줄만 되돌린다
                self._s.add(Document(**vars(doc)))
                self._s.flush()
        except IntegrityError as e:
            name = getattr(getattr(e.orig, "diag", None), "constraint_name", None)
            if name == "uq_documents_case_sha256":
                raise DuplicateDocumentError("같은 사건에 같은 파일이 이미 있음") from e
            raise CaseStoreError(f"저장 실패: {name or e.orig}") from e
        # 자료만 더했으니 실행 id는 비운다 (CaseMaterialsRow 주석)
        row.body = materials.model_dump(mode="json")
        row.run_id = None
        self._s.flush()

    def events(self, case_id: str) -> list[EventRow]:
        q = select(CaseEvent).where(CaseEvent.case_id == case_id)
        rows = [
            EventRow(e.id, e.case_id, e.kind, e.doc_number, e.seq)
            for e in self._s.scalars(q.order_by(CaseEvent.id))
        ]
        return sorted_events(rows)

    def oa_versions(self, case_id: str) -> list[OAVersionRow]:
        q = (
            select(OA, CaseEvent)
            .join(CaseEvent, OA.case_event_id == CaseEvent.id)
            .where(OA.case_id == case_id)
        )
        pairs = sorted(self._s.execute(q).all(), key=lambda p: (p[1].seq is None, p[1].seq or 0))
        out = []
        for oa, event in pairs:
            version = None
            if oa.examined_claim_version_id is not None:
                version = _to_row(self._s.get(ClaimVersion, oa.examined_claim_version_id))
            out.append(
                OAVersionRow(
                    oa.id, event.doc_number, examined_from_version(version), oa.document_id
                )
            )
        return out

    def claim_versions(self, case_id: str) -> list[ClaimVersionRow]:
        q = select(ClaimVersion).where(ClaimVersion.case_id == case_id)
        return [_to_row(v) for v in self._s.scalars(q.order_by(ClaimVersion.version))]

    def ai_input_claim_versions(self, case_id: str) -> list[ClaimVersionRow]:
        return [v for v in self.claim_versions(case_id) if v.source_kind in AI_INPUT_KINDS]

    def _oa(self, case_id: str, dispatch_number: str) -> OA | None:
        number = read_number("dispatch", dispatch_number).value
        if number is None:
            return None
        q = (
            select(OA)
            .join(CaseEvent, OA.case_event_id == CaseEvent.id)
            .where(CaseEvent.case_id == case_id, CaseEvent.kind == "oa")
            .where(CaseEvent.doc_number == number)
        )
        return self._s.scalars(q).one_or_none()

    def examined_claim_version(self, case_id: str, dispatch_number: str) -> ExtractedValue[str]:
        oa = self._oa(case_id, dispatch_number)
        version = None
        if oa is not None and oa.examined_claim_version_id is not None:
            version = _to_row(self._s.get(ClaimVersion, oa.examined_claim_version_id))
        return examined_from_version(version)

    def save_oa_result(
        self, case_id: str, dispatch_number: str, run_id: str, result: OAResult
    ) -> str:
        oa = self._oa(case_id, dispatch_number)
        if oa is None:
            raise CaseStoreError(f"사건 {case_id}에 OA {dispatch_number}가 없음")
        row = oa_result_row(oa.id, run_id, result)
        self._s.add(OAResultRow(**vars(row)))
        self._s.flush()
        return row.id

    def load_oa_result(self, case_id: str, dispatch_number: str) -> OAResult | None:
        oa = self._oa(case_id, dispatch_number)
        if oa is None:
            return None
        # 가장 최근 = created_at이 가장 늦은 것. 한 트랜잭션에서 둘을 넣으면 시각이 같아
        # 고를 수 없다 (실행마다 따로 커밋하면 문제 없음). succeeded 거르기와 함께 #56에서 정한다
        q = (
            select(OAResultRow)
            .where(OAResultRow.oa_id == oa.id)
            .order_by(OAResultRow.created_at.desc())
            .limit(1)
        )
        row = self._s.scalars(q).one_or_none()
        return OAResult.model_validate(row.body) if row else None
