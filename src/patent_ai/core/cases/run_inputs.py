"""실행 입력 만들기 (이슈 #191 T1·T4): OA id로 지휘(run_case)에 넘길 CaseInput과 사건 찾기.

- CaseInput: 사건 id, OA 원문 PDF 경로·문서 id, F3·F4가 읽을 글자(texts).
- texts(OA 당시 청구항 판·최초 명세서)는 #16 T6 저장소가 머지된 뒤 그 판을 읽어 채운다.
  지금은 TextsSource 기본값이 None을 돌려 F3·F4가 "확인되지 않음(input_unverified)"으로 넘겨진다.
  판을 지어내지 않는다 (성공처럼 보이지 않게).
- checked_on(F4 확인 기준일)은 여기서 넣지 않고 실행기가 실행한 날로 넣는다.
실행기가 백그라운드 스레드에서 부르므로 Postgres 구현은 호출마다 새 세션을 연다.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from patent_ai.core.agents.orchestrator import CaseInput
from patent_ai.core.f1_oa_reader.case_repository import DEFAULT_USER_ID
from patent_ai.core.f3_claim_compare.inputs import F3Inputs
from patent_ai.db.models import OA, Case, CaseEvent, Document


class RunInputNotFound(LookupError):
    """OA나 그 원문 문서가 없다 (실행은 failed로 끝난다)."""


class RunInputSource(Protocol):
    def case_input(self, oa_id: str) -> CaseInput:
        """그 OA의 실행 입력. 없으면 RunInputNotFound. checked_on은 비워 둔다 (실행기가 넣음)."""
        ...


class TextsSource(Protocol):
    def texts_for(self, oa_id: str) -> F3Inputs | None:
        """그 OA 당시 청구항 판·최초 명세서 글자. 판을 못 찾으면 None (F3·F4를 넘긴다)."""
        ...


class NoTexts:
    """#16 T6(청구항 판 저장) 전 기본값: 글자를 늘 못 찾는다 → F3·F4는 넘긴 이유가 남는다."""

    def texts_for(self, oa_id: str) -> F3Inputs | None:
        return None


class PostgresRunInputSource:
    def __init__(
        self, session_factory: Callable[[], Session], texts: TextsSource | None = None
    ) -> None:
        self._factory = session_factory
        self._texts = texts or NoTexts()

    def case_input(self, oa_id: str) -> CaseInput:
        with self._factory() as s:
            oa = s.get(OA, oa_id)
            doc = s.get(Document, oa.document_id) if oa and oa.document_id else None
            if oa is None or doc is None:
                raise RunInputNotFound(oa_id)
            case_id, path, doc_id = oa.case_id, doc.path, doc.id
        return CaseInput(
            case_id=case_id,
            oa_document=Path(path),
            oa_document_id=doc_id,
            texts=self._texts.texts_for(oa_id),
        )


class PostgresCaseLookup:
    """지휘의 CaseStore: 같은 OA(출원번호 + 발송번호)·같은 출원번호 사건 찾기 (기본 사용자 안)."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._factory = session_factory

    def find_oa(self, application_number: str, dispatch_number: str) -> tuple[str, str] | None:
        q = (
            select(Case.id, OA.id)
            .join(OA, OA.case_id == Case.id)
            .join(CaseEvent, OA.case_event_id == CaseEvent.id)
            .where(
                Case.user_id == DEFAULT_USER_ID,
                Case.application_number == application_number,
                CaseEvent.doc_number == dispatch_number,
            )
            .limit(1)
        )
        with self._factory() as s:
            row = s.execute(q).first()
        return (row[0], row[1]) if row else None

    def find_case(self, application_number: str) -> str | None:
        q = select(Case.id).where(
            Case.user_id == DEFAULT_USER_ID, Case.application_number == application_number
        )
        with self._factory() as s:
            return s.scalars(q).first()
