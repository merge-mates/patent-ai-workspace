"""올린 사건에 채우기 실제 DB (이슈 #54 task-3, -m db). 끝에 되돌린다.

줄 계산 규칙은 test_case_source_fill.py가 본다. 여기서는 표에 들어가는지·건너뛰는지만.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from patent_ai.core.cases.case_source.fill import PostgresCaseSourceFill
from patent_ai.core.cases.case_source.local_folder import LocalFolderSource
from patent_ai.core.cases.store import NewDocument
from patent_ai.core.cases.store_pg import PostgresCaseAppStore
from patent_ai.core.cases.texts_source import PostgresTextsSource
from patent_ai.core.schemas.common import Status, StatusValue
from patent_ai.core.schemas.document import Page, PageText
from patent_ai.db.models import OA, Case, CaseEvent, ClaimVersion, Document
from patent_ai.settings import get_settings

pytestmark = pytest.mark.db

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
        return sorted((e.kind, e.seq, e.doc_number) for e in rows)


def test_뒤_OA를_채우면_앞_OA_이력_줄은_넣지_않는다(factory, tmp_path):
    oa2 = "952099000540102"
    folder = tmp_path / APP / oa2
    folder.mkdir(parents=True)
    admin = ADMIN + f"{APP}¶{oa2}¶20990901¶의견제출통지서\n"
    (folder / f"{APP}_행정이력.txt").write_text(admin, encoding="utf-8")
    (folder / f"{APP}_청구항이력.txt").write_text(CLAIMS, encoding="utf-8")
    (folder / f"{APP}_출원서_{FILING}.pdf").write_bytes(b"%PDF- fill 54 oa2")
    created = _upload(factory, "fill54_oa2")
    out = PostgresCaseSourceFill(factory, LocalFolderSource(tmp_path)).fill_before_f3(
        created.oa_id, APP, oa2
    )
    assert out.filled
    # 앞 OA(OA_NO) 줄이 없어야 이 사건에 그 OA를 더할 때(add_oa) 줄이 겹치지 않는다
    assert _events(factory, created.case_id) == [("oa", 3, oa2), ("other", 1, None)]


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
