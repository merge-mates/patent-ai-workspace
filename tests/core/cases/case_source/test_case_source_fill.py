"""올린 사건에 채울 줄 계산 (이슈 #54 task-3, DB 없이). 번호는 지어낸 것."""

from datetime import UTC, datetime
from pathlib import Path

from patent_ai.core.cases.case_source.base import Missing, SourceFiles
from patent_ai.core.cases.case_source.cut import lookup_case
from patent_ai.core.cases.case_source.fill import plan_fill
from patent_ai.core.f1_oa_reader.case_repository import StoredFile
from patent_ai.core.schemas.common import UnverifiedReason

APP = "1020990000001"
FILING = "112099000000101"
AMEND = "112099000000202"
OA1 = "952099000000001"
OA2 = "952099000000002"
HEAD = "출원번호¶접수발송번호¶접수발송일자¶접수발송서류명"
CLAIM_HEAD = "출원번호¶접수발송일련번호¶접수발송번호¶청구항번호¶변경구분코드¶변경구분명¶청구항"
FILE = StoredFile(path="x.pdf", sha256="a" * 64, received_at=datetime(2099, 1, 1, tzinfo=UTC))


def admin(*rows):
    return "\n".join([HEAD] + [f"{APP}¶{n}¶2099¶{name}" for n, name in rows])


CLAIMS = "\n".join([CLAIM_HEAD, f"{APP}¶1¶{FILING}¶1¶I¶신규¶가", f"{APP}¶2¶{AMEND}¶1¶U¶보정¶가'"])


class Source:
    name = "fake"

    def __init__(self, admin_text, document=Path("x.pdf")):
        self.files = SourceFiles(admin_text, CLAIMS, document)

    def fetch(self, application_number, dispatch_number):
        return self.files


def _plan(admin_text, dispatch, file=FILE):
    lookup = lookup_case(Source(admin_text), APP, dispatch)
    return plan_fill("c_1", lookup, dispatch, file)


def test_출원_때_판_사건은_판0과_출원서를_잇고_OA는_판0():
    plan = _plan(admin((FILING, "[특허출원]특허출원서"), (OA1, "의견제출통지서")), OA1)
    rows = plan.rows
    assert [(e.kind, e.seq) for e in rows.events] == [("other", 1), ("oa", 2)]
    assert [d.kind for d in rows.documents] == ["spec"]
    (v0,) = rows.claim_versions
    assert (v0.version, v0.source_kind, v0.document_id) == (0, "application", rows.documents[0].id)
    assert plan.examined_claim_version_id == v0.id
    assert plan.target_seq == 2


def test_보정_뒤_OA는_보정_판이_심사_대상이고_뒤_줄은_없다():
    text = admin(
        (FILING, "[특허출원]특허출원서"),
        (OA1, "의견제출통지서"),
        (AMEND, "[명세서등 보정]보정서"),
        (OA2, "의견제출통지서"),
    )
    plan = _plan(text, OA2)
    versions = {v.version: v for v in plan.rows.claim_versions}
    assert versions[1].source_kind == "amendment" and versions[1].source_doc_number == AMEND
    assert versions[1].document_id is None  # 받아 둔 폴더에 보정서 PDF가 없다
    assert plan.examined_claim_version_id == versions[1].id
    # 앞 OA는 이력 줄만, 올린 OA(OA2)가 대상 줄
    assert [e.doc_number for e in plan.rows.events if e.kind == "oa"] == [OA1, OA2]
    plan1 = _plan(text, OA1)
    assert [e.doc_number for e in plan1.rows.events][-1] == OA1  # OA1 뒤 줄은 빠진다
    assert len(plan1.rows.claim_versions) == 1


def test_출원서가_없으면_판0은_문서_없이():
    plan = _plan(admin((FILING, "[특허출원]특허출원서"), (OA1, "의견제출통지서")), OA1, None)
    assert plan.rows.documents == []
    assert plan.rows.claim_versions[0].document_id is None
    assert plan.examined_claim_version_id == plan.rows.claim_versions[0].id


def test_이력을_못_받으면_채울_줄이_없다():
    gone = Missing("admin_history", UnverifiedReason.LOOKUP_FAILED, "없음")
    lookup = lookup_case(Source(gone), APP, OA1)
    assert plan_fill("c_1", lookup, OA1, FILE) is None


def test_발송번호_하이픈도_대상_줄을_찾는다():
    plan = _plan(admin((OA1, "의견제출통지서")), "9-5-2099-000000001")
    assert plan.target_seq == 1
