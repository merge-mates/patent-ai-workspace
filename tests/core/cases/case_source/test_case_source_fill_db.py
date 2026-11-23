"""올린 사건에 채우기 실제 DB (이슈 #54 task-3, -m db). 끝에 되돌린다.

줄 계산 규칙은 test_case_source_fill.py가 본다. 여기서는 표에 들어가는지·건너뛰는지만.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from patent_ai.core.cases.case_fill import PostgresCaseFill
from patent_ai.core.cases.case_source.fill import PostgresCaseSourceFill
from patent_ai.core.cases.case_source.local_folder import LocalFolderSource
from patent_ai.core.cases.run_inputs import PostgresCaseLookup
from patent_ai.core.cases.store import NewDocument
from patent_ai.core.cases.store_pg import PostgresCaseAppStore
from patent_ai.core.cases.texts_source import PostgresTextsSource
from patent_ai.core.schemas.common import Status, StatusValue
from patent_ai.core.schemas.document import Page, PageText
from patent_ai.core.schemas.oa_result import OAResult
from patent_ai.db.models import OA, Case, CaseEvent, ClaimVersion, Document
from patent_ai.settings import get_settings

pytestmark = pytest.mark.db

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "case_missing_citation"
APP = "1020990005401"
FILING = "112099000540101"
OA_NO = "952099000540101"
ADMIN = (
    "출원번호¶접수발송번호¶접수발송일자¶접수발송서류명\n"
    f"{APP}¶{FILING}¶20990101¶[특허출원]특허출원서\n"
    f"{APP}¶{OA_NO}¶20990401¶의견제출통지서\n"
)
CLAIMS = (
    "출원번호¶접수발송일련번호¶접수발송번호¶청구항번호¶변경구분코드¶변경구분명¶청구항\n"
    f"{APP}¶1¶{FILING}¶1¶I¶신규¶가\n"
)


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


@pytest.fixture
def source(tmp_path):
    folder = tmp_path / APP / OA_NO
    folder.mkdir(parents=True)
    (folder / f"{APP}_행정이력.txt").write_text(ADMIN, encoding="utf-8")
    (folder / f"{APP}_청구항이력.txt").write_text(CLAIMS, encoding="utf-8")
    (folder / f"{APP}_출원서_{FILING}.pdf").write_bytes(b"%PDF- fill 54")
    return LocalFolderSource(tmp_path)


def _upload(factory, tag: str):
    with factory() as s:
        created = PostgresCaseAppStore(s).create_case(
            NewDocument(
                path=f"work/uploads/{tag}.pdf",
                sha256=f"{tag}_" + "b" * 20,
                received_at=datetime(2099, 1, 1, tzinfo=UTC),
            )
        )
        s.commit()
    return created


def test_올린_사건에_이력_출원서_판이_들어가고_글자를_만들_수_있다(factory, source):
    created = _upload(factory, "fill54")
    out = PostgresCaseSourceFill(factory, source).fill_before_f3(created.oa_id, APP, OA_NO)
    assert out.filled and out.missing == []
    with factory() as s:
        oa = s.get(OA, created.oa_id)
        event = s.get(CaseEvent, oa.case_event_id)
        assert (event.seq, event.doc_number) == (2, OA_NO)
        events = s.scalars(select(CaseEvent).where(CaseEvent.case_id == created.case_id)).all()
        assert sorted(e.seq for e in events) == [1, 2]  # 올린 OA 줄을 새로 만들지 않음
        (v0,) = s.scalars(select(ClaimVersion).where(ClaimVersion.case_id == created.case_id))
        assert oa.examined_claim_version_id == v0.id
        doc = s.get(Document, v0.document_id)
        assert (doc.kind, doc.source) == ("spec", "api")
        assert s.get(Case, created.case_id).application_number is None  # 번호는 실행 끝 #261

    # 채운 판으로 F3·F4 글자를 만들 수 있다 (PDF 읽기는 가짜)
    def read(path, document_id):
        text = "【청구범위】\n【청구항 1】\n가 장치."
        ok = Status(value=StatusValue.CONFIRMED, checked="가짜 쪽")
        return PageText(
            document_id=document_id,
            pages=[Page(page=1, text=text, status=ok)],
            status=ok,
        )

    texts = PostgresTextsSource(factory, read_pages=read).texts_for(created.oa_id)
    assert texts is not None and texts.claims_document_id == v0.document_id


def test_다시_부르면_이미_채운_사건이라_건너뛴다(factory, source):
    created = _upload(factory, "fill54_again")
    fill = PostgresCaseSourceFill(factory, source)
    assert fill.fill_before_f3(created.oa_id, APP, OA_NO).filled
    again = fill.fill_before_f3(created.oa_id, APP, OA_NO)
    assert not again.filled and again.why == "이미 채운 사건"


def test_같은_출원번호_사건이_따로_있으면_건너뛴다(factory, source):
    other = _upload(factory, "fill54_owner")
    with factory() as s:
        s.get(Case, other.case_id).application_number = APP
        s.commit()
    created = _upload(factory, "fill54_new")
    out = PostgresCaseSourceFill(factory, source).fill_before_f3(created.oa_id, APP, OA_NO)
    assert not out.filled and "같은 출원번호" in out.why
    with factory() as s:
        assert (
            s.scalars(select(ClaimVersion).where(ClaimVersion.case_id == created.case_id)).all()
            == []
        )


def test_받아_둔_폴더에_없으면_아무것도_안_쓰고_이유(factory, tmp_path):
    created = _upload(factory, "fill54_none")
    out = PostgresCaseSourceFill(factory, LocalFolderSource(tmp_path)).fill_before_f3(
        created.oa_id, APP, OA_NO
    )
    assert not out.filled and len(out.missing) == 3
    with factory() as s:
        events = s.scalars(select(CaseEvent).where(CaseEvent.case_id == created.case_id)).all()
        assert [(e.seq, e.doc_number) for e in events] == [(None, None)]


def _events(factory, case_id):
    with factory() as s:
        rows = s.scalars(select(CaseEvent).where(CaseEvent.case_id == case_id)).all()
        return sorted(((e.kind, e.seq, e.doc_number) for e in rows), key=str)


OA2_NO = "952099000540102"


@pytest.fixture
def source2(tmp_path):
    """OA 두 번 사건의 둘째 OA(OA2_NO) 폴더."""
    folder = tmp_path / "oa2" / APP / OA2_NO
    folder.mkdir(parents=True)
    admin = ADMIN + f"{APP}¶{OA2_NO}¶20990901¶의견제출통지서\n"
    (folder / f"{APP}_행정이력.txt").write_text(admin, encoding="utf-8")
    (folder / f"{APP}_청구항이력.txt").write_text(CLAIMS, encoding="utf-8")
    (folder / f"{APP}_출원서_{FILING}.pdf").write_bytes(b"%PDF- fill 54 oa2")
    return LocalFolderSource(tmp_path / "oa2")


ORDERED = [("oa", 2, OA_NO), ("oa", 3, OA2_NO), ("other", 1, None)]


def _result(oa_id: str, dispatch: str) -> OAResult:
    """출원번호 APP·발송번호 dispatch를 읽은 OA 정리."""
    oa = OAResult.model_validate_json((FIXTURE / "oa_result.json").read_text("utf-8"))
    return oa.model_copy(
        update={
            "oa_id": oa_id,
            "application_number": oa.application_number.model_copy(update={"value": APP}),
            "dispatch_number": oa.dispatch_number.model_copy(update={"value": dispatch}),
        }
    )


def _run(factory, source, created, dispatch):
    """실행 한 번에서 사건을 바꾸는 두 단계: F3 앞 채우기 → 실행 끝 번호 채우기."""
    PostgresCaseSourceFill(factory, source).fill_before_f3(created.oa_id, APP, dispatch)
    PostgresCaseFill(factory, lambda oa_id: None).fill_after_f1(
        created.oa_id, created.run_id, _result(created.oa_id, dispatch), None
    )


def _add(factory, case_id, tag):
    with factory() as s:
        added = PostgresCaseAppStore(s).add_oa(
            case_id,
            NewDocument(f"work/uploads/{tag}.pdf", f"{tag}_" + "c" * 20, datetime.now(UTC)),
        )
        s.commit()
    return added


def _seq_of(factory, oa_id):
    """그 OA가 붙은 이력 줄의 (순서, 발송번호). 원문 문서도 같은 줄을 가리켜야 한다."""
    with factory() as s:
        oa = s.get(OA, oa_id)
        event = s.get(CaseEvent, oa.case_event_id)
        assert s.get(Document, oa.document_id).case_event_id == event.id
        return event.seq, event.doc_number


def test_뒤_OA를_채우면_앞_OA_이력_줄도_순서대로_들어간다(factory, source2):
    created = _upload(factory, "fill326")
    out = PostgresCaseSourceFill(factory, source2).fill_before_f3(created.oa_id, APP, OA2_NO)
    assert out.filled
    assert _events(factory, created.case_id) == ORDERED
    with factory() as s:  # 앞 OA는 이력 줄만: 올리지 않은 OA를 만들지 않는다
        assert len(s.scalars(select(OA).where(OA.case_id == created.case_id)).all()) == 1


def test_뒤_OA로_채운_사건에_앞_OA를_새_사건으로_올리면_제자리에_붙는다(factory, source, source2):
    second = _upload(factory, "fill326_m2")
    _run(factory, source2, second, OA2_NO)
    first = _upload(factory, "fill326_m1")
    _run(factory, source, first, OA_NO)
    assert _events(factory, second.case_id) == ORDERED
    assert _seq_of(factory, first.oa_id) == (2, OA_NO)
    assert _seq_of(factory, second.oa_id) == (3, OA2_NO)
    with factory() as s:
        assert s.get(OA, first.oa_id).case_id == second.case_id


def test_뒤_OA로_채운_사건에_앞_OA를_더하면_제자리에_붙는다(factory, source, source2):
    second = _upload(factory, "fill326_a2")
    _run(factory, source2, second, OA2_NO)
    first = _add(factory, second.case_id, "fill326_a1")
    _run(factory, source, first, OA_NO)
    # 올릴 때 만든 번호 빈 줄은 남지 않는다 (같은 OA가 이력에 두 줄로 보이지 않게)
    assert _events(factory, second.case_id) == ORDERED
    assert _seq_of(factory, first.oa_id) == (2, OA_NO)
    # 다시 실행해도 그대로
    _run(factory, source, first, OA_NO)
    assert _events(factory, second.case_id) == ORDERED


def test_앞_OA를_먼저_올렸지만_못_채운_사건도_뒤_OA를_채우면_순서가_맞다(
    factory, source2, tmp_path
):
    # 앞 OA 줄이 순서 없이 이미 있다: 새로 넣으면 unique에 걸리니 그 줄에 순서만 넣는다
    first = _upload(factory, "fill326_p1")
    _run(factory, LocalFolderSource(tmp_path / "none"), first, OA_NO)
    second = _add(factory, first.case_id, "fill326_p2")
    _run(factory, source2, second, OA2_NO)
    assert _events(factory, first.case_id) == ORDERED
    assert _seq_of(factory, first.oa_id) == (2, OA_NO)
    assert _seq_of(factory, second.oa_id) == (3, OA2_NO)


def test_같은_OA를_사건에_다시_더하면_지금처럼_막는다(factory, source2):
    second = _upload(factory, "fill326_d2")
    _run(factory, source2, second, OA2_NO)
    # 지휘의 check_oa가 먼저 찾는다
    assert PostgresCaseLookup(factory).find_oa(APP, OA2_NO) == (second.case_id, second.oa_id)
    # 앞 OA는 이력 줄만 있고 올린 적이 없어 막지 않는다
    assert PostgresCaseLookup(factory).find_oa(APP, OA_NO) is None
    again = _add(factory, second.case_id, "fill326_d2_again")
    with pytest.raises(IntegrityError):  # 검사를 지나쳐도 이미 OA가 있는 줄에는 못 붙는다
        PostgresCaseFill(factory, lambda oa_id: None).fill_after_f1(
            again.oa_id, again.run_id, _result(again.oa_id, OA2_NO), None
        )
    assert _seq_of(factory, second.oa_id) == (3, OA2_NO)
    assert _seq_of(factory, again.oa_id) == (None, None)


def test_쓰다_실패하면_아무것도_남지_않는다(factory, source, monkeypatch):
    from dataclasses import replace

    from patent_ai.core.cases.case_source import fill as fill_module

    real = fill_module.plan_fill

    def broken(*args, **kwargs):
        plan = real(*args, **kwargs)
        bad = [replace(v, document_id="doc_없음") for v in plan.rows.claim_versions]
        return replace(plan, rows=replace(plan.rows, claim_versions=bad))

    monkeypatch.setattr(fill_module, "plan_fill", broken)
    created = _upload(factory, "fill54_broken")
    with pytest.raises(IntegrityError):
        PostgresCaseSourceFill(factory, source).fill_before_f3(created.oa_id, APP, OA_NO)
    assert _events(factory, created.case_id) == [("oa", None, None)]
    with factory() as s:
        kinds = [
            d.kind for d in s.scalars(select(Document).where(Document.case_id == created.case_id))
        ]
        assert kinds == ["oa"]  # 출원서 문서도 되돌려졌다
        assert s.get(OA, created.oa_id).examined_claim_version_id is None
