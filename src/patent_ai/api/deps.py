"""라우터가 쓰는 의존성. 테스트는 dependency_overrides로 메모리 fake·임시 폴더를 끼운다."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from patent_ai.core.cases.materials import CaseMaterialsStore, PostgresCaseMaterialsStore
from patent_ai.core.cases.results import OAResultStore
from patent_ai.core.cases.results_pg import PostgresOAResultStore
from patent_ai.core.cases.run_inputs import PostgresCaseLookup, PostgresRunInputSource
from patent_ai.core.cases.step_results import StepResultStore
from patent_ai.core.cases.step_results_pg import PostgresStepResultStore
from patent_ai.core.cases.store import CaseAppStore
from patent_ai.core.cases.store_pg import PostgresCaseAppStore
from patent_ai.core.f1_oa_reader.case_repository import CaseRepository
from patent_ai.core.f1_oa_reader.case_repository_pg import PostgresCaseRepository
from patent_ai.core.llm.config import REPO_ROOT
from patent_ai.core.llm.limits import CallBudget, RunContext
from patent_ai.core.runs.cancel import CancelRegistry
from patent_ai.core.runs.executor import RunExecutor
from patent_ai.core.runs.launcher import RunLauncher, ThreadLauncher
from patent_ai.core.runs.run_case_executor import RunCaseExecutor
from patent_ai.core.runs.step_log_pg import PostgresCallRecorder, PostgresStepRecorder
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


class CaseRepositoryUnit(Protocol):
    """사건 저장소(#16 묶기 결과) + 트랜잭션 끝내기. 저장소는 flush까지만, 커밋은 라우터가."""

    repo: CaseRepository

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class _PgRepositoryUnit:
    def __init__(self, session: Session) -> None:
        self._session = session
        self.repo: CaseRepository = PostgresCaseRepository(session)

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()


def get_case_repository_unit() -> Iterator[CaseRepositoryUnit]:
    with Session(_engine()) as session:
        yield _PgRepositoryUnit(session)


# --- 실행 (이슈 #57) ---------------------------------------------------------------
# 실행은 백그라운드 스레드에서 돈다. 요청 하나의 세션을 못 쓰니 메서드마다 새 세션을 여는
# 상태 저장소를 앱 전체가 같이 쓴다. 테스트는 dependency_overrides로 메모리 fake를 끼운다.


@lru_cache
def get_run_status_store() -> RunStatusStore:
    return PostgresRunStatusStore(sessionmaker(_engine()))


@lru_cache
def get_oa_result_store() -> OAResultStore:
    """OA 정리 결과 저장소. 결과 받기 API가 읽고, 실행기의 결과 받는 곳(sink)도 이것을 쓴다."""
    return PostgresOAResultStore(sessionmaker(_engine()))


@lru_cache
def get_step_result_store() -> StepResultStore:
    """F3·F4 결과 저장소 (#191). 실행기가 쓰고 결과 API가 읽는다."""
    return PostgresStepResultStore(sessionmaker(_engine()))


@lru_cache
def get_case_materials_store() -> CaseMaterialsStore:
    return PostgresCaseMaterialsStore(sessionmaker(_engine()))


@lru_cache
def get_cancel_registry() -> CancelRegistry:
    """취소 표시는 메모리에 있어서 앱 하나에 하나만 둔다 (요청마다 새로 만들면 안 보인다)."""
    return CancelRegistry()


# 지휘 설정 (plan·순서·넘겨도 되는 단계)
ORCHESTRATOR_CONFIG = REPO_ROOT / "config" / "orchestrator.yaml"


def _new_run_context(run_id: str) -> RunContext:
    """실행마다 새 모델 호출 맥락. 상한은 실행 안에서만 센다 (transport None = 진짜 전송층)."""
    # 모델 호출을 agent_steps에 남긴다. 기록기는 실행마다 새로 (records가 안 섞이게),
    # 엔진은 앱 하나를 같이 쓴다
    return RunContext(
        run_id=run_id,
        budget=CallBudget(),
        recorder=PostgresCallRecorder(sessionmaker(_engine())),
    )


@lru_cache
def _run_case_executor() -> RunCaseExecutor:
    """앱에 하나. 잠금 하나를 같이 써야 "한 번에 하나만 실행"이 지켜진다.

    취소 표시·결과 저장소는 취소 API·결과 API가 쓰는 것과 같은 것을 넘긴다.
    """
    factory = sessionmaker(_engine())
    return RunCaseExecutor(
        store=get_run_status_store(),
        registry=get_cancel_registry(),
        oa_results=get_oa_result_store(),
        step_results=get_step_result_store(),
        # 청구항 판 글자(texts)는 #16 T6 머지 뒤에 넣는다. 그 전에는 F3·F4가 넘긴 이유와 함께 빈다
        inputs=PostgresRunInputSource(factory),
        cases=PostgresCaseLookup(factory),
        config_path=ORCHESTRATOR_CONFIG,
        make_ctx=_new_run_context,
        today=date.today,
        step_log=PostgresStepRecorder(factory),  # 지휘 단계 전부를 agent_steps에
    )


def get_run_executor() -> RunExecutor:
    return _run_case_executor()


def get_run_launcher(
    executor: Annotated[RunExecutor, Depends(get_run_executor)],
    store: Annotated[RunStatusStore, Depends(get_run_status_store)],
) -> RunLauncher:
    return ThreadLauncher(executor, store)
