"""사건 저장소 테스트 (#16 T6). DB 없이 메모리 fake와 표 줄 계산(plan_case_rows)만 본다.

번호는 모두 지어낸 것 (2099년 값, 실제 사건 아님). 실제 DB 왕복은 tests/test_case_repository_db.py.
"""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from patent_ai.core.f1_oa_reader.case_grouping import (
    AS_FILED_VERSION,
    HistoryEvent,
    MaterialInput,
    MissingNotFoundError,
    build_case_materials,
    group_materials,
)
from patent_ai.core.f1_oa_reader.case_repository import (
    CaseRecord,
    CaseStoreError,
    ClaimVersionInput,
    DocumentRow,
    DuplicateDocumentError,
    InMemoryCaseRepository,
    StoredFile,
    UnknownCaseError,
    load_case_view,
    oa_result_row,
    plan_case_rows,
    upload_missing_material,
)
from patent_ai.core.schemas.common import Origin, Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.oa_result import OAResult

APP = "10-2099-0001234"
OA1 = "9-5-2099-000000001"
OA2 = "9-5-2099-000000002"
AMD1 = "1-1-2099-0000001-12"
OTHER_APP = "10-2099-0009999"
CASE_ID = "c_test"


def _m(doc_id, kind, app=APP, number=None, source="uploaded"):
    return MaterialInput(
        document_id=doc_id,
        kind=kind,
        source=source,
        application_number_text=app,
        doc_number_text=number,
    )


def _file(doc_id, sha=None):
    return StoredFile(
        path=f"work/uploads/{doc_id}.pdf",
        sha256=sha or f"sha-{doc_id}",
        received_at=datetime(2099, 1, 1, tzinfo=UTC),
    )


# 이력: OA① → 보정서 → OA②. 자료: OA 둘, 보정서, 출원 청구항, 등록공보 청구항, 인용문헌,
# 그리고 다른 출원번호 자료 하나 (conflict로 남아야 함)
HISTORY = [
    HistoryEvent(kind="oa", doc_number_text=OA1),
    HistoryEvent(kind="amendment", doc_number_text=AMD1),
    HistoryEvent(kind="oa", doc_number_text=OA2),
]
MATERIALS = [
    _m("doc_oa1", "oa", number=OA1),
    _m("doc_amd1", "amendment", number=AMD1),
    _m("doc_oa2", "oa", number=OA2),
    _m("doc_claims_app", "claims"),
    _m("doc_claims_reg", "claims"),
    _m("doc_cit", "citation", app=None, source="api"),
    _m("doc_stray", "oa", app=OTHER_APP, number="9-5-2099-000000009"),
]
CLAIM_INPUTS = [
    ClaimVersionInput(document_id="doc_claims_app", source_kind="application"),
    ClaimVersionInput(
        document_id="doc_claims_reg", source_kind="registration", source_doc_number="1099999"
    ),
]


def _oa() -> OAResult:
    # 빠진 자료 계산에 쓰는 OA 결과. 인용문헌이 없는 가장 작은 OA (fixture를 다시 씀)
    from pathlib import Path

    path = Path(__file__).parents[2] / "fixtures" / "case_missing_citation" / "oa_result.json"
    return OAResult.model_validate_json(path.read_text())


def _record(materials=MATERIALS, history=HISTORY, claims=CLAIM_INPUTS, files=None) -> CaseRecord:
    grouped = group_materials(materials, APP)
    built = build_case_materials(CASE_ID, grouped, [_oa()], received_citations=set())
    return CaseRecord(
        case_id=CASE_ID,
        application_number=APP,
        grouped=grouped,
        files=files
        if files is not None
        else {m.document_id: _file(m.document_id) for m in materials},
        history=history,
        claim_versions=claims,
        materials=built,
    )


# --- 평소: 저장 → 다시 읽기 ---------------------------------------------------


def test_저장하고_다시_읽으면_같은_CaseMaterials():
    repo = InMemoryCaseRepository()
    record = _record()
    repo.save_case(record)
    assert repo.load_case_materials(CASE_ID) == record.materials


def test_저장한_6번에_검토할_사항_목록이_있고_개수와_같다():
    repo = InMemoryCaseRepository()
    repo.save_case(_record())
    got = repo.load_case_materials(CASE_ID)
    assert got.review_items is not None
    assert len(got.review_items) == got.review_items_count


def test_마무리_안_한_6번은_저장_거부():
    # review_items=None = 마무리 안 함. 0건으로 조용히 저장되지 않게 DB에 닿기 전에 막는다
    record = _record()
    unfinished = record.materials.model_copy(update={"review_items": None, "review_items_count": 0})
    with pytest.raises(ValueError, match="review_items"):
        plan_case_rows(record.model_copy(update={"materials": unfinished}))
    with pytest.raises(ValueError, match="review_items"):
        InMemoryCaseRepository().save_case(record.model_copy(update={"materials": unfinished}))


def test_개수와_줄_수가_어긋난_6번은_저장_전에_다시_검사해_거부():
    # model_copy는 검사를 거치지 않아 어긋난 값이 들어올 수 있다: 저장 전에 다시 검사
    record = _record()
    broken = record.materials.model_copy(update={"review_items_count": 99})
    with pytest.raises(ValidationError):
        plan_case_rows(record.model_copy(update={"materials": broken}))


def test_없는_사건은_None():
    assert InMemoryCaseRepository().load_case_materials("c_none") is None


def test_다시_열면_문제_자료의_묶기_상태가_그대로():
    repo = InMemoryCaseRepository()
    repo.save_case(_record())
    docs = {d.document_id: d for d in repo.load_case_materials(CASE_ID).documents}
    assert docs["doc_stray"].status.value == StatusValue.CONFLICT
    assert docs["doc_oa1"].status.value == StatusValue.CONFIRMED


def test_심사_대상_판을_다시_읽음():
    repo = InMemoryCaseRepository()
    repo.save_case(_record())
    first = repo.examined_claim_version(CASE_ID, OA1)
    second = repo.examined_claim_version(CASE_ID, "952099000000002")
    assert (first.value, first.status.value) == (AS_FILED_VERSION, StatusValue.CONFIRMED)
    assert (second.value, second.status.value) == ("112099000000112", StatusValue.CONFIRMED)


def test_이력에_없는_OA는_판을_모름():
    repo = InMemoryCaseRepository()
    repo.save_case(_record(history=[HistoryEvent(kind="oa", doc_number_text=OA1)]))
    v = repo.examined_claim_version(CASE_ID, OA2)
    assert v.value is None
    assert v.status.reason == UnverifiedReason.LOOKUP_FAILED


def test_빈_사건도_저장됨():
    # 자료·이력이 없어도 사건과 출원 때 판(0)은 남는다
    repo = InMemoryCaseRepository()
    empty = CaseRecord(
        case_id=CASE_ID,
        application_number=APP,
        grouped=[],
        files={},
        history=[],
        claim_versions=[],
        materials=build_case_materials(CASE_ID, [], [_oa()], received_citations=set()),
    )
    repo.save_case(empty)
    assert repo.load_case_materials(CASE_ID).documents == []
    assert [(v.version, v.source_kind) for v in repo.claim_versions(CASE_ID)] == [
        (0, "application")
    ]


# --- 두 곳에 있는 값은 한 곳에서 (#120 리뷰 고칠 것 1번) -------------------------


def test_보정서_판_접수번호는_이력_줄에서():
    rows = plan_case_rows(_record())
    events = {e.id: e for e in rows.events}
    (amd,) = [v for v in rows.claim_versions if v.source_kind == "amendment"]
    assert amd.case_event_id is not None
    assert events[amd.case_event_id].kind == "amendment"
    assert amd.source_doc_number == events[amd.case_event_id].doc_number == "112099000000112"


def test_세_표_case_id는_잇는_이력_줄의_case_id():
    rows = plan_case_rows(_record())
    events = {e.id: e for e in rows.events}
    linked = [*rows.oas, *rows.documents, *rows.claim_versions]
    for row in linked:
        if row.case_event_id is not None:
            assert row.case_id == events[row.case_event_id].case_id
    # 이력 줄이 없는 인용문헌 문서·출원 때 판도 같은 사건으로 저장된다
    docs = {d.id: d for d in rows.documents}
    assert docs["doc_cit"].case_event_id is None
    assert docs["doc_cit"].case_id == rows.case.id == CASE_ID
    v0 = next(v for v in rows.claim_versions if v.version == 0)
    assert v0.case_event_id is None and v0.case_id == CASE_ID


def test_이력_순서가_seq로():
    rows = plan_case_rows(_record())
    seq = {(e.kind, e.doc_number): e.seq for e in rows.events}
    assert seq[("oa", "952099000000001")] == 1
    assert seq[("amendment", "112099000000112")] == 2
    assert seq[("oa", "952099000000002")] == 3


def test_OA_줄은_이력_줄과_문서에_이어짐():
    rows = plan_case_rows(_record())
    events = {e.id: e for e in rows.events}
    by_number = {events[o.case_event_id].doc_number: o for o in rows.oas}
    assert by_number["952099000000001"].document_id == "doc_oa1"
    cv = {v.id: v for v in rows.claim_versions}
    assert cv[by_number["952099000000002"].examined_claim_version_id].source_kind == "amendment"
    assert cv[by_number["952099000000001"].examined_claim_version_id].version == 0


# --- 청구항 판 종류와 AI 입력 (#123 리뷰 고칠 것 2번) ----------------------------


def test_등록공보_판은_AI_입력에서_빠짐():
    repo = InMemoryCaseRepository()
    repo.save_case(_record())
    all_kinds = {v.source_kind for v in repo.claim_versions(CASE_ID)}
    ai_kinds = {v.source_kind for v in repo.ai_input_claim_versions(CASE_ID)}
    assert all_kinds == {"application", "amendment", "registration"}
    assert ai_kinds == {"application", "amendment"}


def test_판_종류_없는_청구항_문서는_저장_거부():
    with pytest.raises(CaseStoreError, match="source_kind"):
        plan_case_rows(_record(claims=CLAIM_INPUTS[:1]))  # 등록공보 청구항의 판 종류가 빠짐


def test_모르는_판_종류는_거부():
    with pytest.raises(ValidationError):
        ClaimVersionInput(document_id="doc_claims_app", source_kind="draft")


def test_보정서_판인데_잇는_이력이_없으면_저장_거부():
    materials = [*MATERIALS, _m("doc_claims_amd", "claims")]
    bad = [
        *CLAIM_INPUTS,
        ClaimVersionInput(
            document_id="doc_claims_amd", source_kind="amendment", receipt_number_text=None
        ),
    ]
    with pytest.raises(CaseStoreError, match="이력"):
        plan_case_rows(_record(materials=materials, claims=bad))


def test_보정서_판인데_접수번호가_이력에_없으면_저장_거부():
    materials = [*MATERIALS, _m("doc_claims_amd", "claims")]
    bad = [
        *CLAIM_INPUTS,
        ClaimVersionInput(
            document_id="doc_claims_amd",
            source_kind="amendment",
            receipt_number_text="1-1-2099-0000077-77",
        ),
    ]
    with pytest.raises(CaseStoreError, match="이력"):
        plan_case_rows(_record(materials=materials, claims=bad))


@pytest.mark.parametrize("source_kind", ["application", "registration"])
def test_판이_가리키는_문서가_자료에_없으면_저장_거부(source_kind):
    # 없는 문서를 가리키면 메모리는 들어가고 Postgres는 외래 키에서 깨진다: 저장 코드가 먼저 막는다
    bad = [*CLAIM_INPUTS, ClaimVersionInput(document_id="doc_none", source_kind=source_kind)]
    with pytest.raises(CaseStoreError, match="doc_none"):
        plan_case_rows(_record(claims=bad))


def test_판이_청구항_문서가_아닌_자료를_가리키면_저장_거부():
    # OA 문서를 등록공보 판이라고 하면 안 된다 (청구항 문서 종류 claims·spec만)
    bad = [*CLAIM_INPUTS, ClaimVersionInput(document_id="doc_oa1", source_kind="publication")]
    with pytest.raises(CaseStoreError, match="doc_oa1"):
        plan_case_rows(_record(claims=bad))


def test_같은_청구항_문서에_판이_둘이면_저장_거부():
    bad = [
        *CLAIM_INPUTS,
        ClaimVersionInput(document_id="doc_claims_reg", source_kind="publication"),
    ]
    with pytest.raises(CaseStoreError, match="doc_claims_reg"):
        plan_case_rows(_record(claims=bad))


def test_보정각하된_보정서는_판을_만들지_않음():
    history = [
        HistoryEvent(kind="oa", doc_number_text=OA1),
        HistoryEvent(kind="amendment", doc_number_text=AMD1, dismissed=True),
        HistoryEvent(kind="oa", doc_number_text=OA2),
    ]
    repo = InMemoryCaseRepository()
    repo.save_case(_record(history=history))
    assert "amendment" not in {v.source_kind for v in repo.claim_versions(CASE_ID)}
    assert repo.examined_claim_version(CASE_ID, OA2).value == AS_FILED_VERSION


# --- 실패 ------------------------------------------------------------------------


def test_같은_파일_두_번이면_중복_오류():
    files = {m.document_id: _file(m.document_id) for m in MATERIALS}
    files["doc_oa2"] = _file("doc_oa2", sha=files["doc_oa1"].sha256)
    with pytest.raises(DuplicateDocumentError):
        plan_case_rows(_record(files=files))


def test_파일_정보가_없는_자료는_저장_거부():
    files = {m.document_id: _file(m.document_id) for m in MATERIALS if m.document_id != "doc_cit"}
    with pytest.raises(CaseStoreError, match="doc_cit"):
        plan_case_rows(_record(files=files))


def test_같은_사건을_두_번_저장하면_거부():
    repo = InMemoryCaseRepository()
    repo.save_case(_record())
    with pytest.raises(CaseStoreError):
        repo.save_case(_record())


def test_묶기_결과와_사건_id가_다르면_거부():
    record = _record()
    with pytest.raises(ValidationError):
        CaseRecord(**{**record.model_dump(), "case_id": "c_other"})


# --- OA 결과: status·origin은 모델 값에서 (#120 리뷰 참고 5번) --------------------


def test_OA_결과_줄의_status_origin은_모델에서():
    oa = _oa()
    row = oa_result_row(oa_id="oa_1", run_id="r_1", result=oa)
    assert row.status == oa.status.value
    assert row.origin == oa.origin.value
    assert OAResult.model_validate(row.body) == oa


def test_OA_결과_저장하고_다시_읽기():
    repo = InMemoryCaseRepository()
    repo.save_case(_record())
    edited = _oa().model_copy(update={"origin": Origin.HUMAN_EDITED})
    repo.save_oa_result(CASE_ID, OA1, run_id="r_1", result=_oa())
    repo.save_oa_result(CASE_ID, OA1, run_id="r_2", result=edited)
    # 앞 결과를 지우지 않고, 가장 최근 것을 돌려준다
    assert repo.load_oa_result(CASE_ID, OA1).origin == Origin.HUMAN_EDITED
    assert repo.load_oa_result(CASE_ID, OA2) is None


def test_없는_OA에_결과_저장은_거부():
    repo = InMemoryCaseRepository()
    repo.save_case(_record())
    with pytest.raises(CaseStoreError):
        repo.save_oa_result(CASE_ID, "9-5-2099-000000777", run_id="r_1", result=_oa())


def test_CaseDocument_묶기_상태는_꼭_있음():
    from patent_ai.core.schemas.case_materials import CaseDocument

    with pytest.raises(ValidationError):
        CaseDocument(document_id="d", kind="oa", source="uploaded")
    ok = CaseDocument(
        document_id="d",
        kind="oa",
        source="uploaded",
        status=Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED),
    )
    assert ok.status.reason == UnverifiedReason.NOT_EXTRACTED


# --- 빠진 자료 올리기·사건 보기 (T7) -----------------------------------------------


def _saved_repo() -> InMemoryCaseRepository:
    repo = InMemoryCaseRepository()
    repo.save_case(_record())
    return repo


def test_빠진_자료를_올리면_다시_열어도_그대로():
    repo = _saved_repo()
    before = repo.load_case_materials(CASE_ID)
    what = before.missing[0].what
    got = upload_missing_material(repo, CASE_ID, what, _file("up"), document_id="doc_up")
    again = repo.load_case_materials(CASE_ID)
    assert again == got
    assert what not in {m.what for m in again.missing}
    assert what not in {h.waiting_for for h in again.held_tasks}
    assert again.documents[-1].document_id == "doc_up"
    assert again.documents[-1].source == "uploaded"


def test_올린_자료는_문서_줄로_그_사건에_남는다():
    repo = _saved_repo()
    what = repo.load_case_materials(CASE_ID).missing[0].what
    upload_missing_material(repo, CASE_ID, what, _file("up"), document_id="doc_up")
    rows = repo._cases[CASE_ID]
    (doc,) = [d for d in rows.documents if d.id == "doc_up"]
    assert (doc.case_id, doc.case_event_id, doc.kind) == (CASE_ID, None, "citation")


def test_올린_인용문헌은_문서_줄에_키가_남고_키로_찾는다():
    # #201: 어느 인용문헌 답인지 문서 줄·사건 자료에 남아 F3가 키로 본문 문서를 찾는다
    repo = _saved_repo()
    hit = repo.load_case_materials(CASE_ID).missing[0]
    assert hit.citation_key is not None
    upload_missing_material(repo, CASE_ID, hit.what, _file("up"), document_id="doc_up")
    (doc,) = [d for d in repo._cases[CASE_ID].documents if d.id == "doc_up"]
    assert doc.citation_key == hit.citation_key
    assert repo.load_case_materials(CASE_ID).documents[-1].citation_key == hit.citation_key
    found = repo.citation_document(CASE_ID, hit.citation_key)
    assert found is not None and found.id == "doc_up"


def test_키로_찾을_때_없는_키나_없는_사건이면_None():
    repo = _saved_repo()
    assert repo.citation_document(CASE_ID, "KR20990009999A") is None
    assert repo.citation_document("c_none", "KR20990009999A") is None


def test_같은_키_문서가_둘이면_올린_것을_고른다():
    repo = _saved_repo()
    hit = repo.load_case_materials(CASE_ID).missing[0]
    rows = repo._cases[CASE_ID]
    api_doc = DocumentRow(
        id="doc_api",
        case_id=CASE_ID,
        case_event_id=None,
        kind="citation",
        path="p",
        sha256="sha-api",
        source="api",
        received_at=_file("api").received_at,
        citation_key=hit.citation_key,
    )
    repo._cases[CASE_ID] = replace(rows, documents=[*rows.documents, api_doc])
    upload_missing_material(repo, CASE_ID, hit.what, _file("up"), document_id="doc_up")
    assert repo.citation_document(CASE_ID, hit.citation_key).id == "doc_up"


def test_같은_사건에_같은_파일을_올리면_중복_오류이고_자료는_안_바뀜():
    repo = _saved_repo()
    before = repo.load_case_materials(CASE_ID)
    what = before.missing[0].what
    with pytest.raises(DuplicateDocumentError):
        # 이미 저장된 OA 문서와 같은 파일
        upload_missing_material(repo, CASE_ID, what, _file("x", sha="sha-doc_oa1"))
    assert repo.load_case_materials(CASE_ID) == before


def test_저장된_사건이_없으면_올리기_오류():
    with pytest.raises(UnknownCaseError):
        upload_missing_material(InMemoryCaseRepository(), "c_none", "x", _file("up"))


def test_빠진_자료가_아닌_것을_올리면_오류이고_자료는_안_바뀜():
    repo = _saved_repo()
    before = repo.load_case_materials(CASE_ID)
    with pytest.raises(MissingNotFoundError):
        upload_missing_material(repo, CASE_ID, "D9 없는 문헌 본문", _file("up"))
    assert repo.load_case_materials(CASE_ID) == before


def test_사건_보기_이력은_순서대로_OA별_심사_대상_판():
    repo = _saved_repo()
    events = [(e.kind, e.doc_number, e.seq) for e in repo.events(CASE_ID)]
    assert events[:3] == [
        ("oa", "952099000000001", 1),
        ("amendment", "112099000000112", 2),
        ("oa", "952099000000002", 3),
    ]
    assert all(seq is None for _, _, seq in events[3:])  # 자료로만 온 줄은 뒤에
    versions = [
        (v.dispatch_number, v.examined_claim_version.value) for v in repo.oa_versions(CASE_ID)
    ]
    assert versions == [
        ("952099000000001", AS_FILED_VERSION),
        ("952099000000002", "112099000000112"),
    ]


def test_없는_사건은_이력_판_빈_목록():
    repo = InMemoryCaseRepository()
    assert repo.events("c_none") == [] and repo.oa_versions("c_none") == []
    assert repo.case_application_number("c_none") is None


# 지난 사건: OA① → 보정서① → OA② → 보정서② → 등록결정, 등록공보 판까지 저장 (#54 조회 모양)
AMD2 = "1-1-2099-0000002-34"
LONG_HISTORY = [
    *HISTORY,
    HistoryEvent(kind="amendment", doc_number_text=AMD2),
    HistoryEvent(kind="registration_decision"),
]


def _view(materials):
    repo = InMemoryCaseRepository()
    repo.save_case(_record(materials=materials, history=LONG_HISTORY))
    return load_case_view(repo, CASE_ID)


def test_사건_보기는_가장_늦게_올라온_OA_시점까지_자른다():
    # OA②까지 올라옴: 그 뒤 보정서②·등록결정과 보정서② 판, 등록공보 판이 빠진다
    view = _view(MATERIALS)
    assert [(e.kind, e.seq) for e in view.events if e.seq is not None] == [
        ("oa", 1),
        ("amendment", 2),
        ("oa", 3),
    ]
    assert [(v.version, v.source_kind, v.source_doc_number) for v in view.claim_versions] == [
        (0, "application", None),
        (1, "amendment", "112099000000112"),
    ]


def test_첫_OA만_올라왔으면_그_뒤_보정서와_둘째_OA가_빠진다():
    only_first = [m for m in MATERIALS if m.document_id != "doc_oa2"]
    view = _view(only_first)
    assert [(e.kind, e.seq) for e in view.events if e.seq is not None] == [("oa", 1)]
    assert [v.source_kind for v in view.claim_versions] == ["application"]
    # OA별 심사 대상 판은 자르지 않는다 (OA②의 판도 남음)
    assert [v.dispatch_number for v in view.oa_versions] == ["952099000000001", "952099000000002"]


def test_올라온_OA를_모르면_이력은_그대로이고_공보_판만_빠진다():
    no_oa = [m for m in MATERIALS if m.kind != "oa"]
    view = _view(no_oa)
    assert len([e for e in view.events if e.seq is not None]) == len(LONG_HISTORY)
    assert {v.source_kind for v in view.claim_versions} == {"application", "amendment"}
