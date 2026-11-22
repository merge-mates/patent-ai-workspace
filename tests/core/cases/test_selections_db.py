"""PostgresSelectionStore·runs.kind 실제 DB 저장·읽기 (make test-db). 끝에 되돌린다 (이슈 #70)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from patent_ai.core.cases.selections_pg import PostgresSelectionStore
from patent_ai.core.cases.store import NewDocument
from patent_ai.core.cases.store_pg import PostgresCaseAppStore
from patent_ai.core.runs.store_pg import PostgresRunStatusStore
from patent_ai.core.schemas.common import Origin
from patent_ai.core.schemas.direction import DirectionSelection
from patent_ai.db.models import DirectionSelectionRow
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


def _oa(factory, sha: str):
    with factory() as s:
        created = PostgresCaseAppStore(s).create_case(
            NewDocument(
                path=f"work/uploads/{sha}.pdf",
                sha256=sha + "_" + "a" * 20,
                received_at=datetime(2099, 1, 1, tzinfo=UTC),
            )
        )
        s.commit()
    return created


def test_선택은_그_작은_실행에_묶여_저장되고_다시_읽힌다(factory):
    created = _oa(factory, "db_sel")
    with factory() as s:
        r1 = PostgresCaseAppStore(s).create_run(created.oa_id, kind="redo_drafts")
        r2 = PostgresCaseAppStore(s).create_run(created.oa_id, kind="redo_drafts")
        s.commit()
    store = PostgresSelectionStore(factory)
    pick = DirectionSelection(candidate_id="c1", origin=Origin.HUMAN_SELECTED)
    write = DirectionSelection(written_direction="청구항 1 한정", origin=Origin.HUMAN_WRITTEN)

    store.save_selection(created.oa_id, "u1", pick, run_id=r1.id)
    store.save_selection(created.oa_id, "u2", write, run_id=r2.id)

    assert store.selections_for_run(r1.id) == {"u1": pick}
    assert store.selections_for_run(r2.id) == {"u2": write}
    assert store.selections_for_run("r_없음") == {}


def test_DB가_둘_다_없거나_AI_기본값인_줄을_거부한다(factory):
    created = _oa(factory, "db_sel_ck")
    for row in (
        DirectionSelectionRow(
            oa_id=created.oa_id, run_id=created.run_id, unit_id="u1", origin="human_selected"
        ),
        DirectionSelectionRow(
            oa_id=created.oa_id,
            run_id=created.run_id,
            unit_id="u1",
            candidate_id="c1",
            origin="ai_default",
        ),
    ):
        with factory() as s:
            s.add(row)
            with pytest.raises(IntegrityError):
                s.commit()


def test_실행_종류가_DB에_남는다(factory):
    created = _oa(factory, "db_kind")
    with factory() as s:
        redo = PostgresCaseAppStore(s).create_run(created.oa_id, kind="redo_drafts")
        s.commit()

    statuses = PostgresRunStatusStore(factory)
    assert statuses.get_status(created.run_id).kind == "full"
    assert statuses.get_status(redo.id).kind == "redo_drafts"
    assert redo.kind == "redo_drafts"
