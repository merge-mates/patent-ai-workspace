"""사건·OA·실행 줄 저장소의 Postgres 구현 (이슈 #56 T1). 표 정의는 db/models, 규칙은 store.py.

커밋(트랜잭션 경계)은 부르는 쪽(API)이 정한다. 여기서는 flush까지만.
마이그레이션 없음: #55에서 만든 표를 그대로 쓴다.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from patent_ai.core.cases.store import (
    DEFAULT_STATUS,
    CaseCreated,
    CaseDetailRow,
    CaseNotFoundError,
    CaseSummaryRow,
    DuplicateDocumentError,
    ExistingDocument,
    NewDocument,
    OACreated,
    OADetailRow,
    OARef,
    RunRow,
    RunStore,
    _now,
    case_name_of,
)
from patent_ai.core.f1_oa_reader.case_repository import DEFAULT_USER_ID
from patent_ai.db.models import OA, Case, CaseEvent, Document, OAResultRow, Run


def _run_row(r: Run) -> RunRow:
    return RunRow(r.id, r.oa_id, r.state, r.current_step, r.created_at)


class PostgresRunStore:
    def __init__(self, session: Session, clock: Callable[[], datetime] = _now) -> None:
        self._s = session
        self._clock = clock

    def create_queued(self, oa_id: str) -> RunRow:
        # 시각은 코드에서 정한다 (한 트랜잭션 안에서 둘을 만들어도 시각이 겹치지 않게)
        run = Run(oa_id=oa_id, state="queued", created_at=self._clock())
        self._s.add(run)
        self._s.flush()
        return _run_row(run)

    def latest_for_oa(self, oa_id: str) -> RunRow | None:
        q = (
            select(Run)
            .where(Run.oa_id == oa_id)
            .order_by(Run.created_at.desc(), Run.id.desc())
            .limit(1)
        )
        run = self._s.scalars(q).first()
        return _run_row(run) if run else None


class PostgresCaseAppStore:
    def __init__(
        self,
        session: Session,
        runs: RunStore | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._s = session
        self._clock = clock
        self._runs: RunStore = runs or PostgresRunStore(session, clock)

    def _add_oa(self, case_id: str, file: NewDocument) -> OACreated:
        """이력 줄(번호 비움) → 문서 → OA → queued 실행. 외래 키 순서대로 넣는다."""
        dup = self._s.scalars(
            select(Document.id).where(Document.case_id == case_id, Document.sha256 == file.sha256)
        ).first()
        if dup is not None:
            raise DuplicateDocumentError("같은 사건에 같은 파일이 이미 있음")
        event = CaseEvent(case_id=case_id, kind="oa", doc_number=None)
        self._s.add(event)
        self._s.flush()
        doc = Document(
            case_id=case_id,
            case_event_id=event.id,
            kind="oa",
            path=file.path,
            sha256=file.sha256,
            source="uploaded",
            received_at=file.received_at,
        )
        self._s.add(doc)
        self._s.flush()
        oa = OA(
            case_id=case_id,
            case_event_id=event.id,
            document_id=doc.id,
            created_at=self._clock(),
        )
        self._s.add(oa)
        self._s.flush()
        run = self._runs.create_queued(oa.id)
        return OACreated(oa.id, doc.id, run.id)

    def create_case(self, file: NewDocument) -> CaseCreated:
        # 임시 사건: 출원번호를 모른다 (partial unique라 비어 있는 사건은 여럿이어도 된다)
        case = Case(user_id=DEFAULT_USER_ID, application_number=None)
        self._s.add(case)
        self._s.flush()
        created = self._add_oa(case.id, file)
        return CaseCreated(case.id, created.oa_id, created.document_id, created.run_id)

    def add_oa(self, case_id: str, file: NewDocument) -> OACreated:
        if self._s.get(Case, case_id) is None:
            raise CaseNotFoundError(case_id)
        return self._add_oa(case_id, file)

    def _oas_of(self, case_id: str) -> list[OA]:
        q = select(OA).where(OA.case_id == case_id).order_by(OA.created_at, OA.id)
        return list(self._s.scalars(q))

    def _latest_succeeded_result(self, case_id: str) -> OAResultRow | None:
        """이 사건의 가장 최근 succeeded 실행이 낸 OA 정리. 없으면 None."""
        q = (
            select(OAResultRow)
            .join(Run, OAResultRow.run_id == Run.id)
            .join(OA, OAResultRow.oa_id == OA.id)
            .where(OA.case_id == case_id, Run.state == "succeeded")
            .order_by(OAResultRow.created_at.desc(), OAResultRow.id.desc())
            .limit(1)
        )
        return self._s.scalars(q).first()

    def list_cases(self) -> list[CaseSummaryRow]:
        cases = self._s.scalars(select(Case).where(Case.user_id == DEFAULT_USER_ID))
        rows = []
        for case in cases:
            oas = self._oas_of(case.id)
            if not oas:
                continue  # OA 없는 사건은 이 API로 만들지 않는다
            latest = oas[-1]
            run = self._runs.latest_for_oa(latest.id)
            result = self._latest_succeeded_result(case.id)
            kinds: list[str] = []
            if result is not None:
                for r in result.body.get("rejections", []):
                    if r["kind"] not in kinds:
                        kinds.append(r["kind"])
            rows.append(
                CaseSummaryRow(
                    case_id=case.id,
                    case_name=case_name_of(case.application_number),
                    application_number=case.application_number,
                    latest_oa=OARef(latest.id),
                    rejection_kinds=kinds,
                    run_state=run.state if run else "queued",
                    status=result.status if result else DEFAULT_STATUS,
                    updated_at=latest.created_at,
                )
            )
        return sorted(rows, key=lambda r: r.updated_at, reverse=True)

    def get_case(self, case_id: str) -> CaseDetailRow | None:
        case = self._s.get(Case, case_id)
        if case is None:
            return None
        oas = [OARef(o.id) for o in self._oas_of(case_id)]
        return CaseDetailRow(case.id, case_name_of(case.application_number), oas)

    def get_oa(self, oa_id: str) -> OADetailRow | None:
        oa = self._s.get(OA, oa_id)
        if oa is None:
            return None
        case = self._s.get(Case, oa.case_id)
        event = self._s.get(CaseEvent, oa.case_event_id)
        return OADetailRow(
            oa_id=oa.id,
            case_id=case.id,
            case_name=case_name_of(case.application_number),
            document_id=oa.document_id,
            dispatch_number=event.doc_number if event else None,
            latest_run=self._runs.latest_for_oa(oa.id),
        )

    def find_document_by_sha256(self, sha256: str) -> ExistingDocument | None:
        q = (
            select(Document, OA.id)
            .join(Case, Document.case_id == Case.id)
            .outerjoin(OA, OA.document_id == Document.id)
            .where(Document.sha256 == sha256, Case.user_id == DEFAULT_USER_ID)
            .order_by(Document.created_at, Document.id)
            .limit(1)
        )
        found = self._s.execute(q).first()
        if found is None:
            return None
        doc, oa_id = found
        return ExistingDocument(doc.case_id, oa_id, doc.id)
