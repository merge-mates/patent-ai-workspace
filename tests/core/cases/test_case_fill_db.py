"""PostgresCaseFill 실제 DB (이슈 #261, make test-db). 끝에 되돌린다.

규칙(어떤 번호를 넣는지, 사건 자료 모양)은 test_case_fill.py가 본다. 여기서는 표에 들어가는지만.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from patent_ai.core.cases.case_fill import PostgresCaseFill
from patent_ai.core.cases.materials import PostgresCaseMaterialsStore
from patent_ai.core.cases.store import NewDocument
from patent_ai.core.cases.store_pg import PostgresCaseAppStore
from patent_ai.core.schemas.oa_result import OAResult
from patent_ai.settings import get_settings

pytestmark = pytest.mark.db

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "case_missing_citation"
APP, DISP = "1020990000001", "952099000000001"


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


def _upload(factory, tag: str):
    with factory() as s:
        created = PostgresCaseAppStore(s).create_case(
            NewDocument(
                path=f"work/uploads/{tag}.pdf",
                sha256=f"{tag}_" + "a" * 20,
                received_at=datetime(2099, 1, 1, tzinfo=UTC),
            )
        )
        s.commit()
    return created


def _oa(oa_id: str) -> OAResult:
    oa = OAResult.model_validate_json((FIXTURE / "oa_result.json").read_text("utf-8"))
    return oa.model_copy(update={"oa_id": oa_id})


def test_실행_뒤_사건_이름_발송번호_사건_자료가_채워진다(factory):
    created = _upload(factory, "fill_261")
    PostgresCaseFill(factory, lambda oa_id: None).fill_after_f1(
        created.oa_id, created.run_id, _oa(created.oa_id), None
    )
    with factory() as s:
        store = PostgresCaseAppStore(s)
        assert store.get_case(created.case_id).case_name == APP
        assert store.get_oa(created.oa_id).dispatch_number == DISP
    saved = PostgresCaseMaterialsStore(factory).latest_case_materials(created.case_id)
    assert saved.run_id == created.run_id
    assert [d.document_id for d in saved.result.documents] == [created.document_id]

    # 다시 실행해도 같은 한 줄을 고쳐 쓴다 (문서 줄이 불어나지 않음)
    PostgresCaseFill(factory, lambda oa_id: None).fill_after_f1(
        created.oa_id, created.run_id, _oa(created.oa_id), None
    )
    again = PostgresCaseMaterialsStore(factory).latest_case_materials(created.case_id)
    assert again.result == saved.result


def test_같은_출원번호_사건이_있으면_임시_사건에_번호를_넣지_않는다(factory):
    first = _upload(factory, "fill_261_a")
    fill = PostgresCaseFill(factory, lambda oa_id: None)
    fill.fill_after_f1(first.oa_id, first.run_id, _oa(first.oa_id), None)
    second = _upload(factory, "fill_261_b")
    # 출원번호 unique에 걸려 실패하지 않고, 번호를 넣지 않은 채 남는다 (합치기는 아직 없음)
    fill.fill_after_f1(second.oa_id, second.run_id, _oa(second.oa_id), None)
    with factory() as s:
        assert PostgresCaseAppStore(s).get_case(second.case_id).case_name == "출원번호 확인 전"
    assert PostgresCaseMaterialsStore(factory).latest_case_materials(second.case_id) is None
