"""라우터가 쓰는 의존성. 테스트는 dependency_overrides로 메모리 fake·임시 폴더를 끼운다."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from patent_ai.core.cases.store import CaseAppStore
from patent_ai.core.cases.store_pg import PostgresCaseAppStore
from patent_ai.core.runs.cancel import CancelRegistry
from patent_ai.core.runs.executor import NotConnectedExecutor, RunExecutor
from patent_ai.core.runs.launcher import RunLauncher, ThreadLauncher
from patent_ai.core.runs.store import RunStatusStore
from patent_ai.core.runs.store_pg import PostgresRunStatusStore
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


# --- 실행 (이슈 #57) ---------------------------------------------------------------
# 실행은 백그라운드 스레드에서 돈다. 요청 하나의 세션을 못 쓰니 메서드마다 새 세션을 여는
# 상태 저장소를 앱 전체가 같이 쓴다. 테스트는 dependency_overrides로 메모리 fake를 끼운다.


@lru_cache
def get_run_status_store() -> RunStatusStore:
    return PostgresRunStatusStore(sessionmaker(_engine()))


@lru_cache
def get_cancel_registry() -> CancelRegistry:
    """취소 표시는 메모리에 있어서 앱 하나에 하나만 둔다 (요청마다 새로 만들면 안 보인다)."""
    return CancelRegistry()


def get_run_executor(
    store: Annotated[RunStatusStore, Depends(get_run_status_store)],
) -> RunExecutor:
    # 지휘 에이전트가 아직 안 붙었다: 바로 failed(executor_not_connected). 붙으면 여기만 바꾼다
    return NotConnectedExecutor(store)


def get_run_launcher(
    executor: Annotated[RunExecutor, Depends(get_run_executor)],
    store: Annotated[RunStatusStore, Depends(get_run_status_store)],
) -> RunLauncher:
    return ThreadLauncher(executor, store)
