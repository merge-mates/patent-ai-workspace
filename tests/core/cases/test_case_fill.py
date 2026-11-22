"""F1 뒤 사건 번호 채우기와 사건 자료(⑥) 만들기 (이슈 #261). 확인: uv run pytest -k case_fill

네트워크·DB 없음. Postgres 쪽은 test_case_fill_db.py.
"""

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from patent_ai.core.cases.case_fill import (
    InMemoryCaseFill,
    case_materials_after_f1,
    plan_number_fill,
)
from patent_ai.core.cases.materials import InMemoryCaseMaterialsStore
from patent_ai.core.cases.store import InMemoryCaseAppStore, NewDocument
from patent_ai.core.schemas.case_materials import CaseDocument, CaseMaterials, LookupResult
from patent_ai.core.schemas.common import Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.oa_result import OAResult

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "case_missing_citation"
APP, DISP = "1020990000001", "952099000000001"  # fixture OA가 읽은 번호 (confirmed)
KR, US = "KR20990000001A", "US20990000001A1"  # fixture OA의 인용문헌 D1·D2


def _oa(oa_id: str = "oa_1") -> OAResult:
    oa = OAResult.model_validate_json((FIXTURE / "oa_result.json").read_text("utf-8"))
    return oa.model_copy(update={"oa_id": oa_id})


def _unread(oa: OAResult, field: str) -> OAResult:
    """그 번호 칸을 못 읽은 것으로 바꾼다 (값 없음, unverified)."""
    bad = getattr(oa, field).model_copy(
        update={
            "value": None,
            "status": Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED),
        }
    )
    return oa.model_copy(update={field: bad})


# --- 번호 채우기 ------------------------------------------------------------------


def test_번호를_읽었으면_임시_사건에_출원번호와_OA에_발송번호를_넣는다():
    fill = plan_number_fill("c_1", None, None, _oa(), owner_of_number=None)
    assert (fill.application_number, fill.dispatch_number, fill.case_number) == (APP, DISP, APP)


def test_못_읽은_번호는_넣지_않는다():
    fill = plan_number_fill("c_1", None, None, _unread(_oa(), "application_number"), None)
    assert fill.application_number is None and fill.case_number is None
    assert fill.dispatch_number == DISP  # 발송번호는 읽었으니 넣는다
    fill = plan_number_fill("c_1", APP, None, _unread(_oa(), "dispatch_number"), None)
    assert fill.dispatch_number is None and fill.case_number == APP


def test_충돌인_번호는_값이_있어도_넣지_않는다():
    # 꼭 지킬 선: confirmed가 아닌 번호(conflict)는 값이 남아 있어도 사건에 쓰지 않는다
    oa = _oa()
    conflict = Status(value=StatusValue.CONFLICT)
    oa = oa.model_copy(
        update={
            "application_number": oa.application_number.model_copy(update={"status": conflict}),
            "dispatch_number": oa.dispatch_number.model_copy(update={"status": conflict}),
        }
    )
    assert oa.application_number.value == APP  # 값은 있다
    fill = plan_number_fill("c_1", None, None, oa, None)
    assert (fill.application_number, fill.dispatch_number, fill.case_number) == (None, None, None)


def test_같은_출원번호_사건이_따로_있으면_그_사건에_합치라고_정한다():
    # 임시 사건에 번호를 넣지 않고(출원번호 unique), 기존 사건의 다음 OA로 옮긴다 (#272)
    fill = plan_number_fill("c_tmp", None, None, _oa(), owner_of_number="c_old")
    assert fill.application_number is None
    assert fill.merge_into == "c_old"
    assert fill.case_number == APP  # 합친 사건의 출원번호로 사건 자료를 만든다
    assert fill.dispatch_number == DISP


def test_발송번호를_모르면_합치지_않고_사람_입력을_기다린다():
    # requirements "발송번호가 다를 때" 붙인다: 모르면 같은 OA인지 몰라 임시 사건에 둔다.
    # 사람이 발송번호를 넣어 이어 돌면 그때 합친다 (중복 OA가 기존 사건에 묻히지 않게)
    fill = plan_number_fill("c_tmp", None, None, _unread(_oa(), "dispatch_number"), "c_old")
    assert fill.merge_into is None and fill.application_number is None
    assert fill.case_number is None


def test_합칠_사건이_없으면_merge_into는_비어_있다():
    assert plan_number_fill("c_1", None, None, _oa(), None).merge_into is None
    assert plan_number_fill("c_1", None, None, _oa(), owner_of_number="c_1").merge_into is None


def test_이미_번호가_있는_사건은_바꾸지_않는다(caplog):
    fill = plan_number_fill("c_1", APP, DISP, _oa(), None)
    assert (fill.application_number, fill.dispatch_number, fill.case_number) == (None, None, APP)
    with caplog.at_level(logging.WARNING):
        fill = plan_number_fill("c_1", "1020990000999", None, _oa(), None)
    assert fill.application_number is None and fill.case_number == "1020990000999"
    assert "다름" in caplog.text


# --- 사건 자료 --------------------------------------------------------------------


def test_처음_만든_사건_자료는_OA_원문과_인용문헌마다_올려_주세요다():
    m = case_materials_after_f1("c_1", APP, "doc_1", _oa(), [_oa()], None, None)
    assert [(d.document_id, d.kind, d.status.value) for d in m.documents] == [
        ("doc_1", "oa", StatusValue.CONFIRMED)
    ]
    # 자동 조회(#54) 전이라 받은 본문이 없다: 인용문헌마다 "올려 주세요" + 그 대비만 보류
    assert [(x.citation_key, x.lookup_result, x.ask_upload) for x in m.missing] == [
        (KR, LookupResult.LOOKUP_FAILED, True),
        (US, LookupResult.LOOKUP_FAILED, True),
    ]
    assert [h.task for h in m.held_tasks] == ["f3_compare:oa_1:D1", "f3_compare:oa_1:D2"]
    # 마무리를 거쳐 저장할 수 있는 ⑥이다 (검토할 사항 개수 = 줄 수)
    assert m.review_items is not None and m.review_items_count == len(m.review_items)


def test_글자_추출_상태를_OA_문서_줄에_남긴다():
    scan = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.BODY_MISSING)
    m = case_materials_after_f1("c_1", APP, "doc_1", _oa(), [_oa()], None, scan)
    assert m.documents[0].text_status == scan


def _previous() -> CaseMaterials:
    """앞서 저장된 ⑥: OA 원문 + 받은 KR 본문, US는 #54가 body_missing으로 남김."""
    first = case_materials_after_f1("c_1", APP, "doc_1", _oa(), [_oa()], None, None)
    kr = CaseDocument(
        document_id="doc_kr",
        kind="citation",
        source="api",
        status=Status(value=StatusValue.CONFIRMED, checked="인용문헌: 출원번호로 묶지 않음"),
        citation_key=KR,
    )
    us_missing = first.missing[1].model_copy(update={"lookup_result": LookupResult.BODY_MISSING})
    return CaseMaterials.model_validate(
        first.model_dump()
        | {"documents": [*first.documents, kr], "missing": [us_missing]}
        | {"review_items": None, "review_items_count": 0}
    )


def test_다시_실행해도_문서_줄이_불어나지_않고_받은_본문과_조회_이유를_지킨다():
    m = case_materials_after_f1("c_1", APP, "doc_1", _oa(), [_oa()], _previous(), None)
    assert [d.document_id for d in m.documents] == ["doc_1", "doc_kr"]
    # KR은 받았으니 빠진 자료가 아니고, US는 앞서 남긴 이유(body_missing) 그대로
    assert [(x.citation_key, x.lookup_result) for x in m.missing] == [
        (US, LookupResult.BODY_MISSING)
    ]


def test_같은_사건의_다음_OA는_원문_줄을_더하고_두_OA의_보류를_같이_센다():
    oas = [_oa("oa_1"), _oa("oa_2")]
    m = case_materials_after_f1("c_1", APP, "doc_2", oas[1], oas, _previous(), None)
    assert [d.document_id for d in m.documents] == ["doc_1", "doc_kr", "doc_2"]
    # 같은 US 문헌을 두 OA가 인용: 빠진 자료 한 줄, 보류는 OA마다
    assert [x.depends_on_tasks for x in m.missing] == [["f3_compare:oa_1:D2", "f3_compare:oa_2:D2"]]


# --- 메모리 구현 (실행기 테스트·API 테스트가 쓴다) ----------------------------------


@pytest.fixture
def cases():
    store = InMemoryCaseAppStore()
    created = store.create_case(
        NewDocument("work/u/a.pdf", "a" * 64, datetime(2099, 1, 1, tzinfo=UTC))
    )
    return store, created


def test_메모리_구현은_사건_이름과_발송번호와_사건_자료를_채운다(cases):
    store, created = cases
    materials = InMemoryCaseMaterialsStore()
    oa = _oa(created.oa_id)
    InMemoryCaseFill(store, materials).fill_after_f1(created.oa_id, created.run_id, oa, None)

    assert store.get_case(created.case_id).case_name == APP
    assert store.get_oa(created.oa_id).dispatch_number == DISP
    saved = materials.latest_case_materials(created.case_id)
    assert saved.run_id == created.run_id
    assert [d.document_id for d in saved.result.documents] == [created.document_id]


def test_메모리_구현은_출원번호를_못_읽으면_사건_자료를_만들지_않는다(cases):
    store, created = cases
    materials = InMemoryCaseMaterialsStore()
    oa = _unread(_oa(created.oa_id), "application_number")
    InMemoryCaseFill(store, materials).fill_after_f1(created.oa_id, created.run_id, oa, None)

    assert store.get_case(created.case_id).case_name == "출원번호 확인 전"
    assert materials.latest_case_materials(created.case_id) is None


# --- 같은 출원번호 사건에 합치기 (#272) ----------------------------------------------

DISP2 = "952099000000002"  # 같은 출원의 다음 OA 발송번호


def _next_oa(oa_id: str) -> OAResult:
    """같은 출원번호, 다른 발송번호의 다음 OA 정리."""
    oa = _oa(oa_id)
    return oa.model_copy(
        update={"dispatch_number": oa.dispatch_number.model_copy(update={"value": DISP2})}
    )


def _doc(tag: str) -> NewDocument:
    return NewDocument(f"work/u/{tag}.pdf", tag * 64, datetime(2099, 1, 1, tzinfo=UTC))


@pytest.fixture
def merged():
    """사건 A(번호 채움) 뒤에 같은 출원의 다음 OA를 새 사건으로 올려 실행이 끝난 상태."""
    store = InMemoryCaseAppStore()
    materials = InMemoryCaseMaterialsStore()
    results: dict[str, OAResult] = {}
    fill = InMemoryCaseFill(store, materials, results.get)
    first = store.create_case(_doc("a"))
    results[first.oa_id] = _oa(first.oa_id)
    fill.fill_after_f1(first.oa_id, first.run_id, results[first.oa_id], None)
    second = store.create_case(_doc("b"))
    fill.fill_after_f1(second.oa_id, second.run_id, _next_oa(second.oa_id), None)
    return store, materials, fill, first, second


def test_같은_출원번호면_올린_OA가_기존_사건의_다음_OA가_된다(merged):
    store, _, _, first, second = merged
    case = store.get_case(first.case_id)
    assert [r.oa_id for r in case.oas] == [first.oa_id, second.oa_id]
    oa = store.get_oa(second.oa_id)
    assert (oa.case_id, oa.case_name, oa.dispatch_number) == (first.case_id, APP, DISP2)
    # 원문 문서도 기존 사건으로 옮긴다 (원문 경로는 그대로)
    assert store.get_document_path(second.document_id) == "work/u/b.pdf"
    assert store.find_document_by_sha256("b" * 64).case_id == first.case_id


def test_합친_임시_사건은_사건_목록에서_빠진다(merged):
    store, _, _, first, second = merged
    assert [r.case_id for r in store.list_cases()] == [first.case_id]
    assert store.list_cases()[0].latest_oa.oa_id == second.oa_id


def test_합친_뒤_기존_사건_자료에_새_OA까지_들어간다(merged):
    _, materials, _, first, second = merged
    saved = materials.latest_case_materials(first.case_id)
    assert saved.run_id == second.run_id
    assert [d.document_id for d in saved.result.documents] == [
        first.document_id,
        second.document_id,
    ]
    # 두 OA가 같은 인용문헌을 인용: 빠진 자료 한 줄, 보류는 OA마다
    assert saved.result.missing[0].depends_on_tasks == [
        f"f3_compare:{first.oa_id}:D1",
        f"f3_compare:{second.oa_id}:D1",
    ]
    assert materials.latest_case_materials(second.case_id) is None


def test_기존_사건에_같은_파일이_있으면_합치지_않고_경고를_남긴다(caplog):
    # 올릴 때 409로 막히는 드문 경우 (저장소를 바로 부름): 실패하지 않고 임시 사건 그대로
    store, materials = InMemoryCaseAppStore(), InMemoryCaseMaterialsStore()
    fill = InMemoryCaseFill(store, materials)
    first = store.create_case(_doc("a"))
    fill.fill_after_f1(first.oa_id, first.run_id, _oa(first.oa_id), None)
    second = store.create_case(_doc("a"))
    with caplog.at_level(logging.WARNING):
        fill.fill_after_f1(second.oa_id, second.run_id, _next_oa(second.oa_id), None)
    assert first.case_id in caplog.text
    assert store.get_oa(second.oa_id).case_id == second.case_id
    assert store.get_case(second.case_id).case_name == "출원번호 확인 전"
    assert len(store.list_cases()) == 2


def test_합친_뒤_다시_실행해도_그대로다(merged):
    store, materials, fill, first, second = merged
    before = materials.latest_case_materials(first.case_id).result
    fill.fill_after_f1(second.oa_id, second.run_id, _next_oa(second.oa_id), None)
    assert [r.oa_id for r in store.get_case(first.case_id).oas] == [first.oa_id, second.oa_id]
    assert materials.latest_case_materials(first.case_id).result.documents == before.documents
