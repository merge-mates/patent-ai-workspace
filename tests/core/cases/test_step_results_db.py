"""PostgresStepResultStore 실제 DB 저장·읽기 (make test-db). 끝에 되돌린다 (이슈 #191 T2)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from patent_ai.core.cases.step_results import DuplicateStepResult
from patent_ai.core.cases.step_results_pg import PostgresStepResultStore
from patent_ai.core.cases.store import NewDocument
from patent_ai.core.cases.store_pg import PostgresCaseAppStore
from patent_ai.settings import get_settings
from tests.core.run_case_fakes import real_outcome

pytestmark = pytest.mark.db


@pytest.fixture
def factory():
    engine = create_engine(get_settings().database_url)
    conn = engine.connect()
    outer = conn.begin()
    make = sessionmaker(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield make
    finally:
        outer.rollback()
        conn.close()
        engine.dispose()


def test_step_results_DB에_저장하고_다시_읽으면_같은_객체(factory, tmp_path, monkeypatch):
    outcome = real_outcome(tmp_path, monkeypatch)
    with factory() as s:
        created = PostgresCaseAppStore(s).create_case(
            NewDocument(
                path="work/uploads/db_step.pdf",
                sha256="db_step_" + "a" * 20,
                received_at=datetime(2099, 1, 1, tzinfo=UTC),
            )
        )
        s.commit()
    store = PostgresStepResultStore(factory)
    f3, f4 = outcome.results["run_f3"], outcome.results["run_f4"]
    assert store.step_result(created.run_id, "f3") is None

    store.save_step_result(created.oa_id, created.run_id, f3)
    store.save_step_result(created.oa_id, created.run_id, f4)
    assert store.step_result(created.run_id, "f3") == f3
    assert store.step_result(created.run_id, "f4") == f4
    with pytest.raises(DuplicateStepResult):
        store.save_step_result(created.oa_id, created.run_id, f3)
