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
from patent_ai.db.models import OA, CaseEvent
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


def _next_oa(oa_id: str) -> OAResult:
    """같은 출원번호, 다른 발송번호의 다음 OA."""
    oa = _oa(oa_id)
    return oa.model_copy(
        update={"dispatch_number": oa.dispatch_number.model_copy(update={"value": DISP2})}
    )


DISP2 = "952099000000002"


def test_같은_출원번호_사건이_있으면_올린_OA를_그_사건의_다음_OA로_옮긴다(factory):
    # 출원번호 unique에 걸려 실패하지 않고, 기존 사건으로 옮긴다 (#272)
    first = _upload(factory, "fill_272_a")
    fill = PostgresCaseFill(factory, lambda oa_id: None)
    fill.fill_after_f1(first.oa_id, first.run_id, _oa(first.oa_id), None)
    second = _upload(factory, "fill_272_b")
    fill.fill_after_f1(second.oa_id, second.run_id, _next_oa(second.oa_id), None)
    with factory() as s:
        store = PostgresCaseAppStore(s)
        assert [r.oa_id for r in store.get_case(first.case_id).oas] == [
            first.oa_id,
            second.oa_id,
        ]
        oa = store.get_oa(second.oa_id)
        assert (oa.case_id, oa.dispatch_number) == (first.case_id, DISP2)
        assert store.find_document_by_sha256("fill_272_b_" + "a" * 20).case_id == first.case_id
        # 임시 사건은 지우지 않고 합침 표시 + 목록에서 숨김
        temp = store.get_case(second.case_id)
        assert (temp.oas, temp.merged_into) == ([], first.case_id)
        listed = {r.case_id for r in store.list_cases()}
        assert first.case_id in listed and second.case_id not in listed
        # 기존 사건 이력에 순서가 없으면 옮긴 줄도 비운다 (날짜로 정하지 않음)
        assert s.get(CaseEvent, s.get(OA, second.oa_id).case_event_id).seq is None
    saved = PostgresCaseMaterialsStore(factory).latest_case_materials(first.case_id)
    assert saved.run_id == second.run_id
    assert [d.document_id for d in saved.result.documents] == [
        first.document_id,
        second.document_id,
    ]
    assert PostgresCaseMaterialsStore(factory).latest_case_materials(second.case_id) is None


def _numbered_case(factory, tag: str):
    """번호를 채운 사건 하나 (그 OA 이력 줄에 순서 3)."""
    first = _upload(factory, tag)
    PostgresCaseFill(factory, lambda oa_id: None).fill_after_f1(
        first.oa_id, first.run_id, _oa(first.oa_id), None
    )
    with factory() as s:
        s.get(CaseEvent, s.get(OA, first.oa_id).case_event_id).seq = 3
        s.commit()
    return first


def test_기존_사건_이력에_순서가_있으면_옮긴_OA는_그_다음_순서다(factory):
    first = _numbered_case(factory, "fill_272_seq_a")
    second = _upload(factory, "fill_272_seq_b")
    PostgresCaseFill(factory, lambda oa_id: None).fill_after_f1(
        second.oa_id, second.run_id, _next_oa(second.oa_id), None
    )
    with factory() as s:
        assert s.get(OA, second.oa_id).case_id == first.case_id
        assert s.get(CaseEvent, s.get(OA, second.oa_id).case_event_id).seq == 4


def test_합친_임시_사건에_다음_OA를_올리면_합친_사건에_붙는다(factory):
    first = _numbered_case(factory, "fill_272_add_a")
    second = _upload(factory, "fill_272_add_b")
    PostgresCaseFill(factory, lambda oa_id: None).fill_after_f1(
        second.oa_id, second.run_id, _next_oa(second.oa_id), None
    )
    with factory() as s:
        third = PostgresCaseAppStore(s).add_oa(
            second.case_id,
            NewDocument("work/uploads/fill_272_add_c.pdf", "c" * 30, datetime.now(UTC)),
        )
        s.commit()
        assert PostgresCaseAppStore(s).get_oa(third.oa_id).case_id == first.case_id


def test_기존_사건에_같은_파일이_있으면_합치지_않는다(factory):
    # 올릴 때 409로 막히는 드문 경우 (저장소를 바로 불러 같은 파일 사건을 둘 만든다)
    first = _numbered_case(factory, "fill_272_dup")
    with factory() as s:
        second = PostgresCaseAppStore(s).create_case(
            NewDocument("work/uploads/dup2.pdf", "fill_272_dup_" + "a" * 20, datetime.now(UTC))
        )
        s.commit()
    PostgresCaseFill(factory, lambda oa_id: None).fill_after_f1(
        second.oa_id, second.run_id, _next_oa(second.oa_id), None
    )
    with factory() as s:
        store = PostgresCaseAppStore(s)
        assert store.get_oa(second.oa_id).case_id == second.case_id
        assert store.get_case(second.case_id).merged_into is None
        assert [r.oa_id for r in store.get_case(first.case_id).oas] == [first.oa_id]
