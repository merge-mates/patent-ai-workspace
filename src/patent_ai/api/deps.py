"""라우터가 쓰는 의존성. 테스트는 dependency_overrides로 메모리 fake·임시 폴더를 끼운다."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from patent_ai.core.cases.store import CaseAppStore
from patent_ai.core.cases.store_pg import PostgresCaseAppStore
from patent_ai.settings import get_settings


class CaseUnit(Protocol):
    """요청 하나의 저장소 + 트랜잭션 끝내기. 저장소는 flush까지만 하고 커밋은 라우터가 정한다."""

    store: CaseAppStore

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class _PgUnit:
    def __init__(self, session: Session) -> None:
        self._session = session
        self.store: CaseAppStore = PostgresCaseAppStore(session)

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()


@lru_cache
def _engine() -> Engine:
    return create_engine(get_settings().database_url)


def get_case_unit() -> Iterator[CaseUnit]:
    with Session(_engine()) as session:
        yield _PgUnit(session)


def get_upload_dir() -> Path:
    return Path(get_settings().upload_dir)
