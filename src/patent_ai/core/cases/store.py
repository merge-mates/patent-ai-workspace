"""사건·OA·실행 줄 저장소 인터페이스와 메모리 fake (이슈 #56 T1).

- `RunStore`: runs 줄 쓰기·읽기. 이 이슈는 queued 줄 만들기와 가장 최근 줄 읽기만
  (#57이 상태 바꾸기를 더함).
- `CaseAppStore`: 사건·OA·문서. 실행 줄은 `RunStore`를 불러서 만든다.
- 올릴 때는 출원번호·발송번호를 모른다: 임시 사건(application_number 비움)
  + OA 이력(doc_number 비움).
  F1이 읽은 뒤 채우는 것은 case_fill.py (#261).
- #16 `case_repository`와는 `DEFAULT_USER_ID`, `DuplicateDocumentError`만 같이 쓴다.
- 부르는 방향은 core → db. 이 파일은 DB 연결·표를 쓰지 않고 ID 만들기(`db.ids`)만 가져온다.
  Postgres 구현은 `store_pg.py`.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

from patent_ai.core.f1_oa_reader.case_repository import (
    DEFAULT_USER_ID,
    DuplicateDocumentError,
)
from patent_ai.core.runs.state import UNFINISHED_STATES, RunError, RunState, check_transition
from patent_ai.core.runs.store import RunNotFound, RunStatus, SkippedStep, check_run_kind
from patent_ai.db.ids import new_id

__all__ = [
    "DEFAULT_USER_ID",
    "NO_APPLICATION_NUMBER_NAME",
    "CaseAppStore",
    "CaseCreated",
    "CaseDetailRow",
    "CaseNotFoundError",
    "CaseSummaryRow",
    "DuplicateDocumentError",
    "ExistingDocument",
    "InMemoryCaseAppStore",
    "InMemoryRunStore",
    "NewDocument",
    "OACreated",
    "OADetailRow",
    "OARef",
    "RunRow",
    "RunStore",
    "new_case_id",
    "now_utc",
]

# 출원번호를 읽기 전 사건의 이름 (응답 case_name)
NO_APPLICATION_NUMBER_NAME = "출원번호 확인 전"
# 정리 결과가 아직 없을 때 status 기본값 (StatusValue.UNVERIFIED와 같은 글자)
DEFAULT_STATUS = "unverified"


class CaseNotFoundError(LookupError):
    """없는 사건 (API는 404 case_not_found)."""


# --- 돌려주는 값 ------------------------------------------------------------------


@dataclass(frozen=True)
class NewDocument:
    """올린 파일 한 건. 원본은 디스크, DB에는 경로·해시만."""

    path: str
    sha256: str
    received_at: datetime


@dataclass(frozen=True)
class RunRow:
    id: str
    oa_id: str
    state: str
    current_step: str | None
    created_at: datetime
    kind: str = "full"  # RunKind: full / redo_drafts (#70)


@dataclass(frozen=True)
class OARef:
    """사건 안의 OA 한 줄. notice_kind는 F1 결과가 저장되기 전에는 None."""

    oa_id: str
    notice_kind: str | None = None


@dataclass(frozen=True)
class CaseCreated:
    """POST /cases 결과."""

    case_id: str
    oa_id: str
    document_id: str
    run_id: str


@dataclass(frozen=True)
class OACreated:
    """POST /cases/{id}/oas 결과."""

    oa_id: str
    document_id: str
    run_id: str


@dataclass(frozen=True)
class ExistingDocument:
    """같은 sha256으로 이미 올라온 문서가 있는 곳 (409에 담을 ID)."""

    case_id: str
    oa_id: str | None
    document_id: str


@dataclass(frozen=True)
class CaseSummaryRow:
    """GET /cases 한 줄에 필요한 값."""

    case_id: str
    case_name: str
    application_number: str | None
    latest_oa: OARef
    rejection_kinds: list[str]  # latest_oa의 가장 최근 succeeded 정리에서. 없으면 []
    run_state: str  # latest_oa의 가장 최근 실행 state
    status: str  # latest_oa의 정리 status. 결과 전 unverified
    updated_at: datetime  # 가장 최근 OA를 올린 시각


@dataclass(frozen=True)
class CaseDetailRow:
    """GET /cases/{id}."""

    case_id: str
    case_name: str
    oas: list[OARef]  # 올린 순서


@dataclass(frozen=True)
class OADetailRow:
    """GET /oas/{oa_id}. 발송번호를 모르면 dispatch_number None."""

    oa_id: str
    case_id: str
    case_name: str
    document_id: str | None
    dispatch_number: str | None
    latest_run: RunRow | None


def new_case_id() -> str:
    """사건 ID 만들기 (라우터가 db를 직접 부르지 않게 core에서 준다)."""
    return new_id("c")


def case_name_of(application_number: str | None) -> str:
    return application_number or NO_APPLICATION_NUMBER_NAME


# --- 인터페이스 -------------------------------------------------------------------


class RunStore(Protocol):
    def create_queued(self, oa_id: str, kind: str = "full") -> RunRow:
        """queued 실행 한 줄을 만든다. kind는 RunKind (모르는 값은 ValueError)."""
        ...

    def latest_for_oa(self, oa_id: str) -> RunRow | None:
        """그 OA의 가장 최근 실행 (created_at이 같으면 id가 큰 쪽). 없으면 None."""
        ...


class CaseAppStore(Protocol):
    def create_case(self, file: NewDocument, case_id: str | None = None) -> CaseCreated:
        """임시 사건 + 첫 OA + 문서 + queued 실행. 중복 검사는 부르는 쪽이 find로 먼저.

        case_id를 주면 그 ID로 만든다 (파일 경로에 사건 ID가 들어가서 만들기 전에 정해야 한다).
        """
        ...

    def add_oa(self, case_id: str, file: NewDocument) -> OACreated:
        """같은 사건에 다음 OA. 없는 사건은 CaseNotFoundError,
        같은 사건 안 같은 파일은 DuplicateDocumentError."""
        ...

    def list_cases(self) -> list[CaseSummaryRow]:
        """기본 사용자의 사건. 가장 최근 OA를 올린 사건이 앞."""
        ...

    def get_case(self, case_id: str) -> CaseDetailRow | None: ...

    def get_oa(self, oa_id: str) -> OADetailRow | None: ...

    def create_run(self, oa_id: str, kind: str = "full") -> RunRow:
        """있는 OA에 queued 실행을 하나 더 만든다 (POST /oas/{id}/runs). OA 확인은 부르는 쪽.

        kind = redo_drafts는 사람 방향 선택 뒤 초안만 다시 만드는 작은 실행 (#70)."""
        ...

    def find_document_by_sha256(
        self, sha256: str, case_id: str | None = None
    ) -> ExistingDocument | None:
        """기본 사용자의 모든 사건에서 같은 파일을 찾는다 (DB 제약은 같은 사건 안만 걸려서).
        case_id를 주면 그 사건 안에서만 찾는다."""
        ...

    def get_document_path(self, document_id: str) -> str | None:
        """기본 사용자 사건의 문서 원본 경로 (GET /documents/{id}, #262). 없으면 None."""
        ...


def now_utc() -> datetime:
    return datetime.now(UTC)


# --- 메모리 fake ------------------------------------------------------------------


class InMemoryRunStore:
    """테스트용. 시계와 ID 만들기를 바꿔 끼울 수 있다."""

    def __init__(
        self,
        clock: Callable[[], datetime] = now_utc,
        id_maker: Callable[[], str] = lambda: new_id("r"),
    ) -> None:
        self._clock = clock
        self._id_maker = id_maker
        self._rows: list[RunRow] = []
        # 상태 칸 전체 (RunRow에 없는 waiting_for·error 포함). 실행은 백그라운드 스레드라 잠근다
        self._status: dict[str, RunStatus] = {}
        self._skipped: dict[str, list[SkippedStep]] = {}  # 실행별 넘긴 단계 (기록 순서)
        self._lock = threading.Lock()

    def create_queued(self, oa_id: str, kind: str = "full") -> RunRow:
        check_run_kind(kind)
        row = RunRow(self._id_maker(), oa_id, "queued", None, self._clock(), kind)
        with self._lock:
            self._rows.append(row)
            self._status[row.id] = RunStatus(
                run_id=row.id, oa_id=oa_id, state=RunState.QUEUED, kind=kind
            )
        return row

    def latest_for_oa(self, oa_id: str) -> RunRow | None:
        with self._lock:  # 백그라운드 스레드가 _rows를 바꾸는 중에 읽지 않게 잠근다
            mine = [r for r in self._rows if r.oa_id == oa_id]
            return max(mine, key=lambda r: (r.created_at, r.id), default=None)

    def get_row(self, run_id: str) -> RunRow | None:
        with self._lock:
            return next((r for r in self._rows if r.id == run_id), None)

    # --- RunStatusStore (실행 상태 바꾸기, #57) ---

    def _put(self, status: RunStatus) -> None:
        """상태 칸과 RunRow(state·current_step)를 같이 맞춘다. 잠근 채로 부른다."""
        self._status[status.run_id] = status
        self._rows = [
            replace(r, state=status.state.value, current_step=status.current_step)
            if r.id == status.run_id
            else r
            for r in self._rows
        ]

    def get_status(self, run_id: str) -> RunStatus | None:
        with self._lock:
            return self._status.get(run_id)

    def transition(
        self,
        run_id: str,
        new: RunState,
        *,
        current_step: str | None = None,
        waiting_for: str | None = None,
        error: RunError | None = None,
        expected: RunState | None = None,
    ) -> RunStatus:
        with self._lock:
            cur = self._status.get(run_id)
            if cur is None:
                raise RunNotFound(run_id)
            # 지금 값을 읽어 전이 규칙을 꼭 거친다 (규칙은 state.py 한 곳)
            check_transition(
                cur.state, new, error=error, waiting_for=waiting_for, expected=expected
            )
            updated = cur.model_copy(
                update={
                    "state": new,
                    "current_step": current_step if current_step is not None else cur.current_step,
                    "waiting_for": waiting_for,
                    "error": error.to_dict() if error else None,
                }
            )
            self._put(updated)
            return updated

    def set_current_step(self, run_id: str, step: str) -> None:
        with self._lock:
            cur = self._status.get(run_id)
            if cur is None:
                raise RunNotFound(run_id)
            self._put(cur.model_copy(update={"current_step": step}))

    def record_skipped(self, run_id: str, step: str, reason: str) -> None:
        with self._lock:
            if run_id not in self._status:
                raise RunNotFound(run_id)
            self._skipped.setdefault(run_id, []).append(SkippedStep(step, reason))

    def skipped_steps(self, run_id: str) -> list[SkippedStep]:
        with self._lock:
            return list(self._skipped.get(run_id, []))

    def unfinished_run_ids(self) -> list[str]:
        with self._lock:
            return [r.id for r in self._rows if self._status[r.id].state in UNFINISHED_STATES]


@dataclass
class _Case:
    id: str
    application_number: str | None
    oa_ids: list[str]  # 올린 순서


@dataclass
class _OA:
    id: str
    case_id: str
    document_id: str
    created_at: datetime
    dispatch_number: str | None = None  # 올릴 때는 모른다. F1 뒤 채운다 (#261)


@dataclass
class _Doc:
    id: str
    case_id: str
    sha256: str
    path: str


class InMemoryCaseAppStore:
    """테스트·API 테스트용 메모리 저장소 (DB 없이 돈다).

    결과 저장이 아직 없어 정리 칸은 기본값([]·unverified)이다. 결과 저장이 생기면
    Postgres 쪽처럼 latest_oa의 정리에서만 고른다 (사건 전체에서 고르지 않는다).
    """

    def __init__(
        self,
        runs: RunStore | None = None,
        clock: Callable[[], datetime] = now_utc,
    ) -> None:
        self._runs: RunStore = runs or InMemoryRunStore(clock=clock)
        self._clock = clock
        self._cases: dict[str, _Case] = {}
        self._oas: dict[str, _OA] = {}
        self._docs: list[_Doc] = []

    def _add_oa(self, case: _Case, file: NewDocument) -> OACreated:
        # 같은 사건 안 같은 파일은 거부 (DB의 uq_documents_case_sha256과 같은 규칙)
        if any(d.case_id == case.id and d.sha256 == file.sha256 for d in self._docs):
            raise DuplicateDocumentError("같은 사건에 같은 파일이 이미 있음")
        doc = _Doc(new_id("doc"), case.id, file.sha256, file.path)
        oa = _OA(new_id("oa"), case.id, doc.id, self._clock())
        self._docs.append(doc)
        self._oas[oa.id] = oa
        case.oa_ids.append(oa.id)
        run = self._runs.create_queued(oa.id)
        return OACreated(oa.id, doc.id, run.id)

    def create_case(self, file: NewDocument, case_id: str | None = None) -> CaseCreated:
        case = _Case(case_id or new_id("c"), None, [])
        self._cases[case.id] = case
        created = self._add_oa(case, file)
        return CaseCreated(case.id, created.oa_id, created.document_id, created.run_id)

    def add_oa(self, case_id: str, file: NewDocument) -> OACreated:
        case = self._cases.get(case_id)
        if case is None:
            raise CaseNotFoundError(case_id)
        return self._add_oa(case, file)

    def create_run(self, oa_id: str, kind: str = "full") -> RunRow:
        return self._runs.create_queued(oa_id, kind)

    def _refs(self, case: _Case) -> list[OARef]:
        return [OARef(oa_id) for oa_id in case.oa_ids]

    def list_cases(self) -> list[CaseSummaryRow]:
        rows = []
        for case in self._cases.values():
            latest = self._oas[case.oa_ids[-1]]
            run = self._runs.latest_for_oa(latest.id)
            # 거절이유·status는 latest_oa 기준. 메모리 저장소엔 정리가 없어 늘 기본값
            rows.append(
                CaseSummaryRow(
                    case_id=case.id,
                    case_name=case_name_of(case.application_number),
                    application_number=case.application_number,
                    latest_oa=OARef(latest.id),
                    rejection_kinds=[],
                    run_state=run.state if run else "queued",
                    status=DEFAULT_STATUS,
                    updated_at=latest.created_at,
                )
            )
        return sorted(rows, key=lambda r: r.updated_at, reverse=True)

    def get_case(self, case_id: str) -> CaseDetailRow | None:
        case = self._cases.get(case_id)
        if case is None:
            return None
        return CaseDetailRow(case.id, case_name_of(case.application_number), self._refs(case))

    def get_oa(self, oa_id: str) -> OADetailRow | None:
        oa = self._oas.get(oa_id)
        if oa is None:
            return None
        case = self._cases[oa.case_id]
        return OADetailRow(
            oa_id=oa.id,
            case_id=case.id,
            case_name=case_name_of(case.application_number),
            document_id=oa.document_id,
            dispatch_number=oa.dispatch_number,
            latest_run=self._runs.latest_for_oa(oa.id),
        )

    # --- F1 뒤 번호 채우기 (#261 case_fill.InMemoryCaseFill이 부른다) ---

    def application_number_of(self, case_id: str) -> str | None:
        return self._cases[case_id].application_number

    def case_with_number(self, application_number: str) -> str | None:
        return next(
            (c.id for c in self._cases.values() if c.application_number == application_number),
            None,
        )

    def fill_numbers(
        self, oa_id: str, application_number: str | None, dispatch_number: str | None
    ) -> None:
        oa = self._oas[oa_id]
        if application_number is not None:
            self._cases[oa.case_id].application_number = application_number
        if dispatch_number is not None:
            oa.dispatch_number = dispatch_number

    def find_document_by_sha256(
        self, sha256: str, case_id: str | None = None
    ) -> ExistingDocument | None:
        for d in self._docs:
            if d.sha256 == sha256 and (case_id is None or d.case_id == case_id):
                oa = next((o for o in self._oas.values() if o.document_id == d.id), None)
                return ExistingDocument(d.case_id, oa.id if oa else None, d.id)
        return None

    def get_document_path(self, document_id: str) -> str | None:
        return next((d.path for d in self._docs if d.id == document_id), None)
