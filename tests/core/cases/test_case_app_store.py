"""사건·OA·실행 줄 저장소 (메모리 fake). 파일 내용 없이 sha256 글자만 쓴다."""

from datetime import UTC, datetime

import pytest

from patent_ai.core.cases.store import (
    NO_APPLICATION_NUMBER_NAME,
    CaseNotFoundError,
    InMemoryCaseAppStore,
    InMemoryRunStore,
    NewDocument,
)
from patent_ai.core.f1_oa_reader.case_repository import DuplicateDocumentError

T0 = datetime(2099, 1, 1, tzinfo=UTC)


def _file(sha: str, path: str | None = None) -> NewDocument:
    return NewDocument(path=path or f"work/uploads/{sha}.pdf", sha256=sha, received_at=T0)


def test_만들고_다시_읽으면_같음():
    store = InMemoryCaseAppStore(clock=lambda: T0)
    created = store.create_case(_file("aa"))

    detail = store.get_case(created.case_id)
    assert detail is not None
    assert detail.case_name == NO_APPLICATION_NUMBER_NAME  # 출원번호 모름
    assert [o.oa_id for o in detail.oas] == [created.oa_id]
    assert detail.oas[0].notice_kind is None

    oa = store.get_oa(created.oa_id)
    assert oa is not None
    assert (oa.case_id, oa.document_id, oa.dispatch_number) == (
        created.case_id,
        created.document_id,
        None,
    )
    # 만들 때 queued 실행 한 줄이 같이 생긴다
    assert oa.latest_run is not None
    assert (oa.latest_run.id, oa.latest_run.state) == (created.run_id, "queued")

    [row] = store.list_cases()
    assert row.case_id == created.case_id
    assert row.application_number is None
    assert row.latest_oa.oa_id == created.oa_id
    # 결과가 아직 없으면 기본값
    assert (row.rejection_kinds, row.run_state, row.status) == ([], "queued", "unverified")
    assert row.updated_at == T0


def test_없는_것은_None():
    store = InMemoryCaseAppStore()
    assert store.get_case("c_none") is None
    assert store.get_oa("oa_none") is None
    assert store.find_document_by_sha256("zz") is None
    assert store.list_cases() == []


def test_다음_OA는_같은_사건에_둘째_OA():
    store = InMemoryCaseAppStore()
    first = store.create_case(_file("aa"))
    second = store.add_oa(first.case_id, _file("bb"))

    assert second.oa_id != first.oa_id
    detail = store.get_case(first.case_id)
    assert [o.oa_id for o in detail.oas] == [first.oa_id, second.oa_id]
    oa2 = store.get_oa(second.oa_id)
    assert oa2.case_id == first.case_id
    assert oa2.latest_run.id == second.run_id
    assert len(store.list_cases()) == 1  # 사건은 그대로 하나


def test_없는_사건에_OA_더하기는_없음_오류():
    with pytest.raises(CaseNotFoundError):
        InMemoryCaseAppStore().add_oa("c_none", _file("aa"))


def test_같은_사건에_같은_파일_다시는_중복_오류():
    store = InMemoryCaseAppStore()
    first = store.create_case(_file("aa"))
    with pytest.raises(DuplicateDocumentError):
        store.add_oa(first.case_id, _file("aa", "work/uploads/other.pdf"))


def test_다른_사건에_같은_파일이면_기존_사건을_찾아_줌():
    store = InMemoryCaseAppStore()
    first = store.create_case(_file("aa"))
    store.create_case(_file("bb"))

    found = store.find_document_by_sha256("aa")
    assert found is not None
    assert (found.case_id, found.oa_id, found.document_id) == (
        first.case_id,
        first.oa_id,
        first.document_id,
    )


def test_latest_for_oa는_가장_최근_실행():
    times = iter([datetime(2099, 1, d, tzinfo=UTC) for d in (1, 3, 2)])
    runs = InMemoryRunStore(clock=lambda: next(times))
    a = runs.create_queued("oa_1")
    b = runs.create_queued("oa_1")  # 가장 늦은 시각
    runs.create_queued("oa_1")  # 중간 시각
    assert runs.latest_for_oa("oa_1").id == b.id
    assert a.state == "queued"
    assert runs.latest_for_oa("oa_other") is None


def test_latest_for_oa는_시각이_같으면_id_큰_쪽():
    ids = iter(["r_1", "r_3", "r_2"])
    runs = InMemoryRunStore(clock=lambda: T0, id_maker=lambda: next(ids))
    for _ in range(3):
        runs.create_queued("oa_1")
    assert runs.latest_for_oa("oa_1").id == "r_3"


def test_목록은_가장_최근_OA를_올린_사건이_앞():
    now = [datetime(2099, 1, 1, tzinfo=UTC)]
    store = InMemoryCaseAppStore(runs=InMemoryRunStore(clock=lambda: T0), clock=lambda: now[0])
    old = store.create_case(_file("aa"))  # 1일
    now[0] = datetime(2099, 1, 2, tzinfo=UTC)
    store.create_case(_file("bb"))  # 2일
    now[0] = datetime(2099, 1, 3, tzinfo=UTC)
    second = store.add_oa(old.case_id, _file("cc"))  # 3일: 먼저 만든 사건에 둘째 OA

    rows = store.list_cases()
    assert rows[0].case_id == old.case_id
    assert rows[0].updated_at == datetime(2099, 1, 3, tzinfo=UTC)
    assert rows[0].latest_oa.oa_id == second.oa_id
