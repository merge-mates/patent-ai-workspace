"""올린 사건에 조회 결과를 채운다 (이슈 #54 1단계). F1이 번호를 읽은 뒤, F3 앞에서 부른다.

- 조회(`lookup_case`)로 OA 시점까지 자른 이력·출원서를 받아 `CaseRecord`를 만들고, 표 줄은
  사건 저장과 같은 `plan_case_rows`로 계산한다 (저장 규칙이 둘로 갈라지지 않게).
- 올린 임시 사건(#56)에 더한다: 이력 줄, 출원서 문서, 청구항 판. 올린 OA 이력 줄은 새로 만들지
  않고 그 줄에 순서(seq)·발송번호를 넣고, 그 OA에 심사 대상 판을 잇는다.
  앞 OA 이력 줄도 순서대로 넣는다 (OA는 만들지 않는다). 그 OA를 나중에 올리면 실행 끝 case_fill이
  같은 발송번호 줄에 붙인다 (합치기 #303, 사건에 OA 더하기 #326). 앞 OA를 먼저 올려 줄이 이미
  있으면 새로 넣지 않고 그 줄에 순서만 넣는다.
- 사건 출원번호·사건 자료(⑥)는 여기서 쓰지 않는다. 실행 끝의 case_fill(#261)이 쓴다.
- 건너뛰는 경우 (이유를 돌려준다, 조용히 넘기지 않음):
  이미 판이 있는 사건(다시 실행·평가 저장·같은 사건 둘째 OA), 같은 출원번호 사건이 따로 있음
  (#272 합치기와 겹치지 않게), 조회로 이력을 못 받음.
- 쓰다 실패하면 그 사건 줄을 모두 되돌리고 예외를 올린다 (실행은 failed).
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from patent_ai.core.cases.case_source.base import CaseSource, Missing
from patent_ai.core.cases.case_source.cut import CaseLookup, lookup_case
from patent_ai.core.cases.store import now_utc
from patent_ai.core.f1_oa_reader.case_grouping import MaterialInput, group_materials, read_number
from patent_ai.core.f1_oa_reader.case_repository import (
    DEFAULT_USER_ID,
    CaseRecord,
    CaseRows,
    ClaimVersionInput,
    StoredFile,
    plan_case_rows,
)
from patent_ai.core.schemas.case_materials import CaseMaterials
from patent_ai.db.ids import new_id
from patent_ai.db.models import OA, Case, CaseEvent, ClaimVersion, Document
from patent_ai.git_paths import REPO_ROOT

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FillOutcome:
    """채우기 결과. filled=False면 why에 이유. missing은 조회로 못 가져온 것 (채웠어도 남음)."""

    filled: bool
    missing: list[Missing] = field(default_factory=list)
    why: str | None = None


@dataclass(frozen=True)
class FillPlan:
    """올린 사건에 더할 줄. oa_event 칸은 올린 OA 이력 줄에 넣을 값."""

    rows: CaseRows  # plan_case_rows 결과 (사건 줄·OA 줄·⑥은 쓰지 않는다)
    target_event_id: str  # rows.events 중 올린 OA 이력 줄에 해당하는 줄 (새로 넣지 않음)
    target_seq: int | None
    examined_claim_version_id: str | None  # 올린 OA의 심사 대상 판 (모르면 None)


def plan_fill(
    case_id: str,
    lookup: CaseLookup,
    dispatch_number: str,
    file: StoredFile | None,
) -> FillPlan | None:
    """조회 결과 → 더할 줄. 자른 이력이 없으면 None. file은 출원서 파일 정보 (없으면 None)."""
    if lookup.cut is None:
        return None
    dispatch_number = read_number("dispatch", dispatch_number).value or dispatch_number
    app = lookup.application_number
    grouped, claim_versions, files = [], [], {}
    if file is not None:
        doc_id = new_id("doc")
        grouped = group_materials(
            [
                MaterialInput(
                    document_id=doc_id, kind="spec", source="api", application_number_text=app
                )
            ],
            app,
        )
        claim_versions = [ClaimVersionInput(document_id=doc_id, source_kind="application")]
        files = {doc_id: file}
    record = CaseRecord(
        case_id=case_id,
        application_number=app,
        grouped=grouped,
        files=files,
        history=lookup.cut.history,
        claim_versions=claim_versions,
        # plan_case_rows가 마무리한 ⑥(review_items 있음)을 요구한다. 여기서는 쓰지 않는다
        # (⑥은 실행 끝 case_fill이 만든다). 빈 결과로 모으면 "결과 0개" 경고만 남아 빈 목록을 준다
        materials=CaseMaterials(case_id=case_id, review_items=[], review_items_count=0),
    )
    rows = plan_case_rows(record)
    target = next(
        (e for e in rows.events if e.kind == "oa" and e.doc_number == dispatch_number), None
    )
    if target is None:  # cut_at_oa가 대상 OA를 마지막 줄로 남기므로 버그일 때만
        raise ValueError("자른 이력에 대상 OA 줄이 없음")
    oa = next((o for o in rows.oas if o.case_event_id == target.id), None)
    return FillPlan(
        rows=rows,
        target_event_id=target.id,
        target_seq=target.seq,
        examined_claim_version_id=oa.examined_claim_version_id if oa else None,
    )


def stored_file(path: Path) -> StoredFile:
    """출원서 파일 정보. DB에는 경로·해시만 둔다 (원본은 받아 둔 폴더 그대로).

    저장소 안이면 저장소 뿌리 기준 상대 경로로 둔다 (올린 OA `work/uploads/…`와 같이, 서버를
    컨테이너(/app)에서 돌리든 맥에서 돌리든 같은 줄이 읽히게).
    """
    try:
        shown = str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        shown = str(path)
    return StoredFile(
        path=shown,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        received_at=now_utc(),
    )


class PostgresCaseSourceFill:
    """실행 스레드에서 부르므로 호출마다 새 세션을 열고 커밋한다 (case_fill.py와 같은 방식)."""

    def __init__(self, session_factory: Callable[[], Session], source: CaseSource) -> None:
        self._factory = session_factory
        self._source = source

    def fill_before_f3(
        self, oa_id: str, application_number: str, dispatch_number: str
    ) -> FillOutcome:
        with self._factory() as s:
            oa = s.get(OA, oa_id)
            if oa is None:
                raise LookupError(f"OA가 없음: {oa_id}")
            case_id = oa.case_id
            has_versions = s.scalars(
                select(ClaimVersion.id).where(ClaimVersion.case_id == case_id).limit(1)
            ).first()
            if has_versions is not None:
                why = (
                    "이미 채운 사건"
                    if oa.examined_claim_version_id
                    else ("사건에 이미 청구항 판이 있어 이 OA는 안 채움 (같은 사건 둘째 OA는 후속)")
                )
                return FillOutcome(False, why=why)
            owner = s.scalars(
                select(Case.id).where(
                    Case.user_id == DEFAULT_USER_ID,
                    Case.application_number == application_number,
                    Case.id != case_id,
                )
            ).first()
            if owner is not None:
                return FillOutcome(
                    False, why="같은 출원번호 사건이 따로 있어 채우지 않음 (#272 합치기 뒤)"
                )

        # 파일 읽기·해시는 세션 밖에서 한다 (DB 연결을 오래 잡지 않게)
        lookup = lookup_case(self._source, application_number, dispatch_number)
        file = stored_file(lookup.application_document) if lookup.application_document else None
        plan = plan_fill(case_id, lookup, dispatch_number, file)
        if plan is None:
            return FillOutcome(False, lookup.missing, "조회로 이력을 받지 못해 채우지 않음")

        with self._factory() as s:
            oa = s.get(OA, oa_id)
            event = s.get(CaseEvent, oa.case_event_id)
            if event.doc_number not in (None, dispatch_number):
                raise ValueError("올린 OA 이력 줄의 발송번호가 읽은 발송번호와 다름")
            rows = plan.rows
            # plan 안 OA 이력 줄 id → 올린 OA 이력 줄 id (판·문서가 그 줄을 가리키면 바꿔 단다)
            remap = {plan.target_event_id: event.id}
            event.seq, event.doc_number = plan.target_seq, dispatch_number
            # 먼저 올린 앞 OA의 줄 (발송번호 → 줄). 순서를 모르던 줄이라 순서만 넣는다
            own_oas = {
                e.doc_number: e
                for e in s.scalars(
                    select(CaseEvent).where(
                        CaseEvent.case_id == oa.case_id,
                        CaseEvent.kind == "oa",
                        CaseEvent.doc_number.is_not(None),
                        CaseEvent.id != event.id,
                    )
                )
            }
            for e in rows.events:
                if e.id == plan.target_event_id:
                    continue
                known = own_oas.get(e.doc_number) if e.kind == "oa" else None
                if known is not None:
                    known.seq = e.seq
                    remap[e.id] = known.id
                else:
                    s.add(CaseEvent(**vars(e)))
            s.flush()
            for d in rows.documents:
                s.add(
                    Document(
                        **(vars(d) | {"case_event_id": remap.get(d.case_event_id, d.case_event_id)})
                    )
                )
            s.flush()
            for v in rows.claim_versions:
                s.add(
                    ClaimVersion(
                        **(vars(v) | {"case_event_id": remap.get(v.case_event_id, v.case_event_id)})
                    )
                )
            s.flush()
            oa.examined_claim_version_id = plan.examined_claim_version_id
            s.commit()  # 위에서 실패하면 커밋 없이 세션이 닫혀 모두 되돌려진다
        logger.info(
            "사건 %s: %s로 이력 %d줄·판 %d개를 채움 (못 가져온 것 %d)",
            case_id,
            self._source.name,
            len(rows.events),
            len(rows.claim_versions),
            len(lookup.missing),
        )
        return FillOutcome(True, lookup.missing)
