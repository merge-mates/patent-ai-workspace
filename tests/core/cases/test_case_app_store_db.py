"""PostgresCaseAppStore: 실제 DB 왕복과 sha256 찾기 (make test-db). 끝에 되돌린다."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from patent_ai.core.cases.store import NO_APPLICATION_NUMBER_NAME, NewDocument
from patent_ai.core.cases.store_pg import PostgresCaseAppStore, PostgresRunStore
from patent_ai.core.f1_oa_reader.case_repository import DuplicateDocumentError
from patent_ai.db.models import OA, Case, CaseEvent
from patent_ai.settings import get_settings

pytestmark = pytest.mark.db

T0 = datetime(2099, 1, 1, tzinfo=UTC)


def _file(sha: str) -> NewDocument:
    return NewDocument(path=f"work/uploads/{sha}.pdf", sha256=sha, received_at=T0)


@pytest.fixture
def session():
    engine = create_engine(get_settings().database_url)
    conn = engine.connect()
    outer = conn.begin()
    sess = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield sess
    finally:
        sess.close()
        outer.rollback()
        conn.close()
        engine.dispose()


def test_만들고_다시_읽으면_같음(session):
    store = PostgresCaseAppStore(session)
    sha = "db_roundtrip_" + "a" * 20
    created = store.create_case(_file(sha))
    second = store.add_oa(created.case_id, _file(sha + "2"))
    session.expire_all()

    # 임시 사건: 출원번호 없음, OA 이력은 번호 없이
    assert session.get(Case, created.case_id).application_number is None
    events = list(session.scalars(select(CaseEvent).where(CaseEvent.case_id == created.case_id)))
    assert {(e.kind, e.doc_number) for e in events} == {("oa", None)}
    assert session.get(OA, created.oa_id).document_id == created.document_id

    detail = store.get_case(created.case_id)
    assert detail.case_name == NO_APPLICATION_NUMBER_NAME
    assert [o.oa_id for o in detail.oas] == [created.oa_id, second.oa_id]
    oa = store.get_oa(second.oa_id)
    assert (oa.case_id, oa.latest_run.id, oa.latest_run.state) == (
        created.case_id,
        second.run_id,
        "queued",
    )
    row = next(r for r in store.list_cases() if r.case_id == created.case_id)
    assert (row.rejection_kinds, row.status, row.run_state) == ([], "unverified", "queued")

    with pytest.raises(DuplicateDocumentError):
        store.add_oa(created.case_id, _file(sha))


def test_sha256로_기존_문서_찾기(session):
    store = PostgresCaseAppStore(session)
    sha = "db_find_" + "b" * 20
    created = store.create_case(_file(sha))
    found = store.find_document_by_sha256(sha)
    assert (found.case_id, found.oa_id, found.document_id) == (
        created.case_id,
        created.oa_id,
        created.document_id,
    )
    assert store.find_document_by_sha256("db_none_" + "c" * 20) is None


def test_latest_for_oa는_시각이_같으면_id_큰_쪽(session):
    # 시계를 고정해 실행 셋의 시각을 모두 같게 만든다
    runs = PostgresRunStore(session, clock=lambda: T0)
    store = PostgresCaseAppStore(session, runs=runs)
    created = store.create_case(_file("db_run_" + "d" * 20))
    ids = [created.run_id] + [runs.create_queued(created.oa_id).id for _ in range(2)]
    assert runs.latest_for_oa(created.oa_id).id == max(ids)
