"""PostgresCaseRepository: 실제 DB 왕복과 보정서 판 CHECK (make test-db).

번호는 모두 지어낸 것 (2099년 값). 바깥 트랜잭션을 끝에 되돌려 DB에 남기지 않는다.
"""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from patent_ai.core.f1_oa_reader.case_grouping import AS_FILED_VERSION
from patent_ai.core.f1_oa_reader.case_repository import (
    CaseStoreError,
    DuplicateDocumentError,
    upload_missing_material,
)
from patent_ai.core.f1_oa_reader.case_repository_pg import PostgresCaseRepository
from patent_ai.core.schemas.common import StatusValue
from patent_ai.db.models import OA, CaseMaterialsRow, ClaimVersion, Document, OAResultRow, Run
from patent_ai.settings import get_settings
from tests.core.f1.test_case_repository import CASE_ID, OA1, OA2, _file, _oa, _record

pytestmark = pytest.mark.db


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


def test_저장하고_다시_읽으면_같음(session):
    repo = PostgresCaseRepository(session)
    record = _record()
    repo.save_case(record)
    session.expire_all()  # 메모리에 남은 객체가 아니라 DB에서 다시 읽게

    assert repo.load_case_materials(CASE_ID) == record.materials
    assert repo.examined_claim_version(CASE_ID, OA1).value == AS_FILED_VERSION
    second = repo.examined_claim_version(CASE_ID, OA2)
    assert (second.value, second.status.value) == ("112099000000112", StatusValue.CONFIRMED)
    assert {v.source_kind for v in repo.ai_input_claim_versions(CASE_ID)} == {
        "application",
        "amendment",
    }
    # 세 표 case_id가 모두 이 사건
    for model in (OA, Document, ClaimVersion):
        assert set(session.scalars(select(model.case_id))) <= {CASE_ID}


def test_OA_결과_status_origin은_본문과_같음(session):
    repo = PostgresCaseRepository(session)
    repo.save_case(_record())
    oa_id = session.scalars(select(OA.id)).first()
    session.add(Run(id="r_test", oa_id=oa_id, state="succeeded"))
    session.flush()
    repo.save_oa_result(CASE_ID, OA1, run_id="r_test", result=_oa())

    row = session.scalars(select(OAResultRow)).one()
    assert row.status == row.body["status"]["value"]
    assert row.origin == row.body["origin"]
    assert repo.load_oa_result(CASE_ID, OA1) == _oa()


def test_같은_사건_두_번은_거부(session):
    repo = PostgresCaseRepository(session)
    repo.save_case(_record())
    with pytest.raises(CaseStoreError):
        repo.save_case(_record())


def test_같은_파일은_DB에서도_중복_오류(session):
    # 저장 코드 검사를 건너뛰고 DB unique가 막는지 본다
    repo = PostgresCaseRepository(session)
    repo.save_case(_record())
    existing = session.scalars(select(Document)).first()
    session.add(
        Document(
            case_id=existing.case_id,
            kind="citation",
            path="work/uploads/again.pdf",
            sha256=existing.sha256,
            source="uploaded",
            received_at=existing.received_at,
        )
    )
    with pytest.raises(IntegrityError, match="uq_documents_case_sha256"):
        session.flush()


def test_보정서_판인데_이력_줄이_없으면_CHECK가_거부(session):
    repo = PostgresCaseRepository(session)
    repo.save_case(_record())
    session.add(
        ClaimVersion(
            case_id=CASE_ID,
            version=99,
            source_kind="amendment",
            source_doc_number="112099000000999",
            case_event_id=None,
        )
    )
    with pytest.raises(IntegrityError, match="ck_claim_versions_amendment_event"):
        session.flush()


# --- 빠진 자료 올리기·사건 보기 (T7) -----------------------------------------------


def test_빠진_자료를_올리면_DB에서_다시_읽어도_그대로(session):
    repo = PostgresCaseRepository(session)
    repo.save_case(_record())
    what = repo.load_case_materials(CASE_ID).missing[0].what
    got = upload_missing_material(repo, CASE_ID, what, _file("up"), document_id="doc_up")
    session.expire_all()

    assert repo.load_case_materials(CASE_ID) == got
    doc = session.get(Document, "doc_up")
    assert (doc.case_id, doc.case_event_id, doc.kind, doc.source) == (
        CASE_ID,
        None,
        "citation",
        "uploaded",
    )
    assert session.get(CaseMaterialsRow, CASE_ID).run_id is None  # 자료만 더함


def test_같은_사건에_같은_파일을_올리면_중복_오류이고_자료는_안_바뀜(session):
    repo = PostgresCaseRepository(session)
    repo.save_case(_record())
    before = repo.load_case_materials(CASE_ID)
    with pytest.raises(DuplicateDocumentError):
        upload_missing_material(
            repo, CASE_ID, before.missing[0].what, _file("x", sha="sha-doc_oa1")
        )
    session.expire_all()
    assert repo.load_case_materials(CASE_ID) == before


def test_사건_보기_이력과_OA별_판(session):
    repo = PostgresCaseRepository(session)
    repo.save_case(_record())
    session.expire_all()
    seq = [(e.kind, e.doc_number, e.seq) for e in repo.events(CASE_ID)][:3]
    assert seq == [
        ("oa", "952099000000001", 1),
        ("amendment", "112099000000112", 2),
        ("oa", "952099000000002", 3),
    ]
    versions = [
        (v.dispatch_number, v.examined_claim_version.value) for v in repo.oa_versions(CASE_ID)
    ]
    assert versions == [
        ("952099000000001", AS_FILED_VERSION),
        ("952099000000002", "112099000000112"),
    ]
