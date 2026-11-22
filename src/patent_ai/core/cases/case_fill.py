"""실행이 끝난 뒤 F1이 읽은 번호를 사건에 넣고 사건 자료(⑥)를 만든다 (이슈 #261).

올릴 때는 출원번호·발송번호를 모른다 (임시 사건, store.py). 실행기가 OA 정리를 저장한 뒤
이 모듈의 `CaseFillSink.fill_after_f1`을 불러:
1. 번호 채우기: 출원번호가 confirmed이고 사건에 아직 없으면 사건에, 발송번호가 confirmed이면
   그 OA 이력 줄에 넣는다. 읽지 못한(unverified·conflict) 번호는 넣지 않는다 (지어내지 않음).
2. 사건 자료 저장: 사건 출원번호를 알 때만 만든다 (묶기가 출원번호로 자료를 맞춰 보기 때문).
   자동 조회(#54) 전이라 인용문헌 본문은 받은 것이 없어 "올려 주세요"(lookup_failed)로 남는다.
   #54가 붙으면 받은 인용문헌과 못 받은 이유를 이 자리로 넘긴다.

하지 않는 것 (조용히 넘기지 않고 경고를 남긴다):
- 같은 출원번호 사건이 이미 있을 때 기존 사건에 합치기 (F1 requirements "실패할 때").
  지금은 임시 사건에 번호를 넣지 않고 그대로 둔다 (DB의 출원번호 unique 때문에 넣을 수도 없다).
- 사건 출원번호와 다른 번호를 읽었을 때 사건 번호 바꾸기.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from patent_ai.core.cases.materials import InMemoryCaseMaterialsStore, SavedCaseMaterials
from patent_ai.core.f1_oa_reader.case_grouping import (
    MaterialInput,
    build_case_materials,
    group_materials,
)
from patent_ai.core.f1_oa_reader.case_repository import DEFAULT_USER_ID
from patent_ai.core.schemas.case_materials import CaseMaterials, LookupResult
from patent_ai.core.schemas.common import ExtractedValue, Status, StatusValue
from patent_ai.core.schemas.oa_result import OAResult
from patent_ai.core.schemas.propagation import finalize_case_materials
from patent_ai.db.models import OA, Case, CaseEvent, CaseMaterialsRow

logger = logging.getLogger(__name__)


class CaseFillSink(Protocol):
    """실행기가 OA 정리를 저장한 뒤 부르는 곳. 실패하면 예외를 올린다 (실행은 failed)."""

    def fill_after_f1(
        self, oa_id: str, run_id: str, result: OAResult, text_status: Status | None
    ) -> None: ...


# --- 계산 (DB 없이 테스트한다) ----------------------------------------------------

# 사건 자료가 아직 없을 때 404 result_not_ready 메시지 (이유 없는 404가 되지 않게)
NOT_READY_NO_NUMBER = (
    "출원번호 확인 전이라 사건 자료를 만들지 않았습니다 "
    "(실행 전이거나, 출원번호를 못 읽었거나, 같은 출원번호 사건이 이미 있음)"
)
NOT_READY = "사건 자료가 아직 없습니다 (실행이 끝나기 전)"


def materials_not_ready_message(application_number_known: bool) -> str:
    """사건 자료가 없는 이유. 출원번호를 모르면 묶기를 못 해 만들지 않는다."""
    return NOT_READY if application_number_known else NOT_READY_NO_NUMBER


@dataclass(frozen=True)
class NumberFill:
    """채울 번호. None이면 그 칸은 그대로 둔다."""

    application_number: str | None  # 사건에 넣을 출원번호
    dispatch_number: str | None  # OA 이력 줄에 넣을 발송번호
    case_number: str | None  # 채운 뒤 사건 출원번호 (모르면 None: 사건 자료를 못 만든다)


def _confirmed(v: ExtractedValue[str]) -> str | None:
    return v.value if v.status.value == StatusValue.CONFIRMED and v.value else None


def plan_number_fill(
    case_id: str,
    case_number: str | None,
    event_number: str | None,
    result: OAResult,
    owner_of_number: str | None,
) -> NumberFill:
    """F1 결과에서 채울 번호를 고른다.

    case_number·event_number: 지금 사건 출원번호·OA 이력 줄 발송번호.
    owner_of_number: 읽은 출원번호를 이미 가진 다른 사건 id (없으면 None).
    """
    app = _confirmed(result.application_number)
    disp = _confirmed(result.dispatch_number)
    fill_app = None
    if app is not None and case_number is None:
        if owner_of_number is not None and owner_of_number != case_id:
            # 합치기는 아직 없다: 번호를 넣지 않고 남긴다 (조용히 넘기지 않게 경고)
            logger.warning(
                "사건 %s: 출원번호 %s의 사건 %s가 이미 있어 번호를 넣지 않음 (합치기 미구현)",
                case_id,
                app,
                owner_of_number,
            )
        else:
            fill_app = app
    elif app is not None and case_number != app:
        logger.warning(
            "사건 %s: 사건 출원번호 %s와 읽은 출원번호 %s가 다름 (사건 번호는 그대로)",
            case_id,
            case_number,
            app,
        )
    fill_disp = disp if disp is not None and event_number is None else None
    return NumberFill(fill_app, fill_disp, case_number or fill_app)


def case_materials_after_f1(
    case_id: str,
    case_number: str,
    oa_document_id: str,
    result: OAResult,
    case_oas: list[OAResult],
    previous: CaseMaterials | None,
    text_status: Status | None,
) -> CaseMaterials:
    """사건 자료(⑥)를 이번 OA 정리까지 넣어 다시 만든다.

    - previous(앞서 저장된 ⑥)의 문서 줄은 그대로 둔다 (올린 인용문헌·#16 묶기 결과를 잃지 않게).
      이번 OA 원문이 아직 없을 때만 문서 줄을 더한다 (다시 실행해도 줄이 불어나지 않음).
    - 빠진 자료·보류 작업은 사건의 OA 정리 전부(case_oas, 이번 것 포함)로 다시 계산한다.
      앞서 남긴 조회 이유(#54가 넣은 body_missing 등)는 그대로 쓴다.
    - 인용문헌 본문은 저장된 문서 줄의 키로만 받은 것으로 친다
      (자동 조회 전이라 그 밖은 lookup_failed).
    """
    kept = list(previous.documents) if previous else []
    new = []
    if oa_document_id not in {d.document_id for d in kept}:
        material = MaterialInput(
            document_id=oa_document_id,
            kind="oa",
            source="uploaded",
            application_number_text=result.application_number.raw_text
            or result.application_number.value,
            doc_number_text=result.dispatch_number.raw_text or result.dispatch_number.value,
        )
        new = group_materials([material], case_number)
    received = {d.citation_key for d in kept if d.kind == "citation" and d.citation_key}
    failures: dict[str, LookupResult] = {
        m.citation_key: m.lookup_result
        for m in (previous.missing if previous else [])
        if m.citation_key
    }
    statuses = {oa_document_id: text_status} if text_status is not None else {}
    built = build_case_materials(case_id, new, case_oas, received, failures, statuses)
    merged = CaseMaterials.model_validate(
        built.model_dump() | {"documents": [*kept, *built.documents]}
    )
    # 문서 줄을 합쳤으니 검토할 사항을 다시 모은다 (개수 = 줄 수 검사도 다시)
    return finalize_case_materials(case_oas, merged)


def _case_oas(order: list[str], current: OAResult, others: dict[str, OAResult]) -> list[OAResult]:
    """사건 OA 순서대로 정리를 모은다. 이번 OA는 손에 든 결과, 나머지는 저장된 결과."""
    out = []
    for oa_id in order:
        if oa_id == current.oa_id:
            out.append(current)
        elif oa_id in others:
            out.append(others[oa_id])
        else:
            logger.warning("사건 자료: OA %s의 정리가 아직 없어 빠진 자료 검사에서 뺌", oa_id)
    return out


# --- Postgres ---------------------------------------------------------------------


class PostgresCaseFill:
    """실행 스레드에서 부르므로 호출마다 새 세션을 열고 커밋한다 (results_pg.py와 같은 방식).

    latest_result: oa_id → 그 OA에서 보여 줄 가장 최근 정리 (다른 OA의 정리를 읽는 데 쓴다).
    """

    def __init__(
        self,
        session_factory: Callable[[], Session],
        latest_result: Callable[[str], OAResult | None],
    ) -> None:
        self._factory = session_factory
        self._latest = latest_result

    def fill_after_f1(
        self, oa_id: str, run_id: str, result: OAResult, text_status: Status | None
    ) -> None:
        with self._factory() as s:
            oa = s.get(OA, oa_id)
            if oa is None:
                raise LookupError(f"OA가 없음: {oa_id}")
            case = s.get(Case, oa.case_id)
            event = s.get(CaseEvent, oa.case_event_id)
            app = _confirmed(result.application_number)
            owner = None
            if app is not None and case.application_number is None:
                owner = s.scalars(
                    select(Case.id).where(
                        Case.user_id == DEFAULT_USER_ID, Case.application_number == app
                    )
                ).first()
            fill = plan_number_fill(
                case.id, case.application_number, event.doc_number, result, owner
            )
            if fill.application_number is not None:
                case.application_number = fill.application_number
            if fill.dispatch_number is not None:
                event.doc_number = fill.dispatch_number
            s.flush()

            if fill.case_number is None:
                logger.info("사건 %s: 출원번호를 몰라 사건 자료를 아직 만들지 않음", case.id)
                s.commit()
                return
            order = list(
                s.scalars(select(OA.id).where(OA.case_id == case.id).order_by(OA.created_at, OA.id))
            )
            others = {o: r for o in order if o != oa_id and (r := self._latest(o)) is not None}
            row = s.get(CaseMaterialsRow, case.id)
            previous = CaseMaterials.model_validate(row.body) if row else None
            body = case_materials_after_f1(
                case.id,
                fill.case_number,
                oa.document_id,
                result,
                _case_oas(order, result, others),
                previous,
                text_status,
            ).model_dump(mode="json")
            if row is None:
                s.add(CaseMaterialsRow(case_id=case.id, body=body, run_id=run_id))
            else:
                row.body, row.run_id = body, run_id
            s.commit()


# --- 메모리 (테스트용) --------------------------------------------------------------


class InMemoryCaseFill:
    """InMemoryCaseAppStore·InMemoryCaseMaterialsStore에 같은 규칙으로 채운다."""

    def __init__(
        self,
        cases,  # InMemoryCaseAppStore (순환 import를 피하려고 이름만)
        materials: InMemoryCaseMaterialsStore,
        latest_result: Callable[[str], OAResult | None] = lambda oa_id: None,
    ) -> None:
        self._cases = cases
        self._materials = materials
        self._latest = latest_result
        self._lock = threading.Lock()

    def fill_after_f1(
        self, oa_id: str, run_id: str, result: OAResult, text_status: Status | None
    ) -> None:
        with self._lock:
            oa = self._cases.get_oa(oa_id)
            if oa is None:
                raise LookupError(f"OA가 없음: {oa_id}")
            app = _confirmed(result.application_number)
            fill = plan_number_fill(
                oa.case_id,
                self._cases.application_number_of(oa.case_id),
                oa.dispatch_number,
                result,
                self._cases.case_with_number(app) if app else None,
            )
            self._cases.fill_numbers(oa_id, fill.application_number, fill.dispatch_number)
            if fill.case_number is None:
                return
            order = [r.oa_id for r in self._cases.get_case(oa.case_id).oas]
            others = {o: r for o in order if o != oa_id and (r := self._latest(o)) is not None}
            saved: SavedCaseMaterials | None = self._materials.latest_case_materials(oa.case_id)
            body = case_materials_after_f1(
                oa.case_id,
                fill.case_number,
                oa.document_id,
                result,
                _case_oas(order, result, others),
                saved.result if saved else None,
                text_status,
            )
            self._materials.put(oa.case_id, run_id, body)
