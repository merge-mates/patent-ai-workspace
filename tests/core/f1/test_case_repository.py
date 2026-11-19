"""사건 저장소 테스트 (#16 T6). DB 없이 메모리 fake와 표 줄 계산(plan_case_rows)만 본다.

번호는 모두 지어낸 것 (2099년 값, 실제 사건 아님). 실제 DB 왕복은 tests/test_case_repository_db.py.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from patent_ai.core.f1_oa_reader.case_grouping import (
    APPLICATION_VERSION,
    HistoryEvent,
    MaterialInput,
    build_case_materials,
    group_materials,
)
from patent_ai.core.f1_oa_reader.case_repository import (
    CaseRecord,
    CaseStoreError,
    ClaimVersionInput,
    DuplicateDocumentError,
    InMemoryCaseRepository,
    StoredFile,
    oa_result_row,
    plan_case_rows,
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
    built = build_case_materials(CASE_ID, grouped, _oa(), received_citations=set())
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
    assert (first.value, first.status.value) == (APPLICATION_VERSION, StatusValue.CONFIRMED)
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
        materials=build_case_materials(CASE_ID, [], _oa(), received_citations=set()),
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
    bad = [
        *CLAIM_INPUTS,
        ClaimVersionInput(
            document_id="doc_claims_app", source_kind="amendment", receipt_number_text=None
        ),
    ]
    with pytest.raises(CaseStoreError, match="이력"):
        plan_case_rows(_record(claims=bad))


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


def test_보정각하된_보정서는_판을_만들지_않음():
    history = [
        HistoryEvent(kind="oa", doc_number_text=OA1),
        HistoryEvent(kind="amendment", doc_number_text=AMD1, dismissed=True),
        HistoryEvent(kind="oa", doc_number_text=OA2),
    ]
    repo = InMemoryCaseRepository()
    repo.save_case(_record(history=history))
    assert "amendment" not in {v.source_kind for v in repo.claim_versions(CASE_ID)}
    assert repo.examined_claim_version(CASE_ID, OA2).value == APPLICATION_VERSION


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
