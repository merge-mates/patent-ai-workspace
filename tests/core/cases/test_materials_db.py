"""PostgresCaseMaterialsStore 실제 DB 읽기 (make test-db). 끝에 되돌린다."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from patent_ai.core.cases.materials import PostgresCaseMaterialsStore
from patent_ai.core.cases.store import NewDocument
from patent_ai.core.cases.store_pg import PostgresCaseAppStore
from patent_ai.core.schemas.case_materials import CaseMaterials
from patent_ai.db.models import CaseMaterialsRow
from patent_ai.settings import get_settings

pytestmark = pytest.mark.db

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "case_missing_citation"


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


def test_저장된_줄을_읽고_없으면_None(factory):
    body = CaseMaterials.model_validate_json((FIXTURE / "case_materials.json").read_text("utf-8"))
    with factory() as s:
        created = PostgresCaseAppStore(s).create_case(
            NewDocument(
                path="work/uploads/db_mat.pdf",
                sha256="db_mat_" + "a" * 20,
                received_at=datetime(2099, 1, 1, tzinfo=UTC),
            )
        )
        s.commit()
    store = PostgresCaseMaterialsStore(factory)
    assert store.latest_case_materials(created.case_id) is None

    with factory() as s:
        s.add(
            CaseMaterialsRow(
                case_id=created.case_id, body=body.model_dump(mode="json"), run_id=created.run_id
            )
        )
        s.commit()
    got = store.latest_case_materials(created.case_id)
    assert got.run_id == created.run_id and got.result == body
