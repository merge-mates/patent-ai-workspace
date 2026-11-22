"""PostgresHumanInputStore 실제 DB 저장·읽기 (make test-db). 끝에 되돌린다 (이슈 #70 계획 ②)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from patent_ai.core.cases.human_inputs_pg import PostgresHumanInputStore
from patent_ai.core.cases.store import NewDocument
from patent_ai.core.cases.store_pg import PostgresCaseAppStore
from patent_ai.db.models import HumanInputRow
from patent_ai.settings import get_settings

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


def _created(factory):
    with factory() as s:
        created = PostgresCaseAppStore(s).create_case(
            NewDocument(
                path="work/uploads/db_hin.pdf",
                sha256="db_hin_" + "a" * 20,
                received_at=datetime(2099, 1, 1, tzinfo=UTC),
            )
        )
        s.commit()
    return created


def test_번호와_맞아요를_저장하고_다시_읽는다(factory):
    c = _created(factory)
    store = PostgresHumanInputStore(factory)
    assert store.confirmed_at(c.oa_id, c.run_id) is None

    store.add(c.oa_id, c.run_id, "application_number", "1020990000001")
    store.add(c.oa_id, c.run_id, "dispatch_number", "952099000000001")
    at = store.add(c.oa_id, c.run_id, "oa_result_confirmed", None)

    assert store.numbers_for_run(c.run_id) == {
        "application_number": "1020990000001",
        "dispatch_number": "952099000000001",
    }
    assert store.confirmed_at(c.oa_id, c.run_id) == at


def test_DB가_값_모양이_틀린_줄을_거부한다(factory):
    c = _created(factory)
    for row in (
        HumanInputRow(oa_id=c.oa_id, run_id=c.run_id, kind="application_number", value=None),
        HumanInputRow(oa_id=c.oa_id, run_id=c.run_id, kind="oa_result_confirmed", value="x"),
    ):
        with factory() as s:
            s.add(row)
            with pytest.raises(IntegrityError):
                s.commit()
