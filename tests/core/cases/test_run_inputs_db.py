"""실행 입력·사건 찾기 Postgres 구현 (make test-db). 끝에 되돌린다 (이슈 #191 T1)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from patent_ai.core.cases.run_inputs import (
    PostgresCaseLookup,
    PostgresRunInputSource,
    RunInputNotFound,
)
from patent_ai.core.cases.store import NewDocument
from patent_ai.core.cases.store_pg import PostgresCaseAppStore
from patent_ai.db.models import OA, Case, CaseEvent
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


def _upload(factory):
    with factory() as s:
        created = PostgresCaseAppStore(s).create_case(
            NewDocument(
                path="work/uploads/db_input.pdf",
                sha256="db_input_" + "a" * 20,
                received_at=datetime(2099, 1, 1, tzinfo=UTC),
            )
        )
        s.commit()
    return created


def test_올린_OA의_실행_입력은_사건_문서_경로이고_글자는_없다(factory):
    created = _upload(factory)
    got = PostgresRunInputSource(factory).case_input(created.oa_id)
    assert got.case_id == created.case_id
    assert got.oa_document == Path("work/uploads/db_input.pdf")
    assert got.oa_document_id == created.document_id
    assert got.texts is None and got.checked_on is None  # 판을 지어내지 않는다


def test_없는_OA면_RunInputNotFound(factory):
    with pytest.raises(RunInputNotFound):
        PostgresRunInputSource(factory).case_input("oa_없음")


def test_번호가_채워진_OA와_사건을_찾는다(factory):
    created = _upload(factory)
    lookup = PostgresCaseLookup(factory)
    assert lookup.find_case("2099-0000001") is None
    with factory() as s:
        s.get(Case, created.case_id).application_number = "2099-0000001"
        oa = s.get(OA, created.oa_id)
        s.get(CaseEvent, oa.case_event_id).doc_number = "9-5-2099-000000001"
        s.commit()
    assert lookup.find_case("2099-0000001") == created.case_id
    assert lookup.find_oa("2099-0000001", "9-5-2099-000000001") == (
        created.case_id,
        created.oa_id,
    )
    assert lookup.find_oa("2099-0000001", "다른 발송번호") is None
