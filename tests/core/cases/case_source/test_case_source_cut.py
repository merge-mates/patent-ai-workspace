"""OA 시점 자르기·파서 (이슈 #54 task-1). 번호·글자는 지어낸 것."""

from pathlib import Path

import pytest

from patent_ai.core.cases.case_source.base import Missing, SourceFiles
from patent_ai.core.cases.case_source.cut import cut_at_oa, lookup_case
from patent_ai.core.cases.case_source.parse import (
    SourceFormatError,
    parse_admin_history,
    parse_claim_history,
)
from patent_ai.core.schemas.common import UnverifiedReason

APP = "1020990000001"
FILING = "112099000000101"  # 출원서 접수번호
AMEND1 = "112099000000202"  # OA1 앞 보정서 (청구항 바꿈)
FORMAL = "112099000000303"  # OA1 앞 보정서 (청구항 안 바꿈)
OA1 = "952099000000001"
AMEND2 = "112099000000404"  # OA1 뒤 보정서
OA2 = "952099000000002"

ADMIN_HEAD = "출원번호¶접수발송번호¶접수발송일자¶접수발송서류명¶처리상태"
CLAIM_HEAD = "출원번호¶접수발송일련번호¶접수발송번호¶청구항번호¶변경구분코드¶변경구분명¶청구항"


def admin_text(rows: list[tuple[str, str, str]]) -> str:
    return "\n".join([ADMIN_HEAD] + [f"{APP}¶{n}¶{d}¶{name}¶수리" for n, d, name in rows])


def claim_text(rows: list[tuple[str, str, str]]) -> str:
    lines = [CLAIM_HEAD]
    for i, (receipt, no, text) in enumerate(rows, start=1):
        lines.append(f"{APP}¶{i}¶{receipt}¶{no}¶I¶신규¶{text}<br />")
    return "\n".join(lines)


ADMIN = admin_text(
    [
        (FILING, "20990101", "[특허출원]특허출원서"),
        (AMEND1, "20990201", "[명세서등 보정]보정서"),
        (FORMAL, "20990301", "[출원서 등 보정]보정서"),
        (OA1, "20990401", "의견제출통지서"),
        (AMEND2, "20990501", "[명세서등 보정]보정서"),
        (OA2, "20990601", "의견제출통지서"),
    ]
)
CLAIMS = claim_text(
    [(FILING, "1", "가"), (FILING, "2", "나"), (AMEND1, "1", "가'"), (AMEND2, "1", "가''")]
)


def _cut(admin=ADMIN, claims=CLAIMS, dispatch=OA1):
    return cut_at_oa(parse_admin_history(admin), parse_claim_history(claims), dispatch)


def test_대상_OA_뒤_줄과_뒤_보정_청구항이_빠진다():
    cut = _cut()
    assert [r.number for r in cut.admin] == [FILING, AMEND1, FORMAL, OA1]
    assert {c.receipt_number for c in cut.claim_changes} == {FILING, AMEND1}
    assert [e.kind for e in cut.history] == ["other", "amendment", "other", "oa"]


def test_청구항을_안_바꾼_보정서는_판을_만들지_않는다():
    kinds = {e.doc_number_text: e.kind for e in _cut().history}
    assert kinds[FORMAL] == "other"


def test_날짜가_거꾸로여도_줄_순서로_자른다():
    admin = admin_text(
        [
            (FILING, "20990901", "[특허출원]특허출원서"),
            (OA1, "20990101", "의견제출통지서"),
            (AMEND1, "20990102", "[명세서등 보정]보정서"),
        ]
    )
    cut = _cut(admin=admin)
    assert [r.number for r in cut.admin] == [FILING, OA1]
    assert {c.receipt_number for c in cut.claim_changes} == {FILING}


def test_두번째_OA는_앞_보정을_모두_남긴다():
    cut = _cut(dispatch=OA2)
    assert cut.admin[-1].number == OA2
    assert {c.receipt_number for c in cut.claim_changes} == {FILING, AMEND1, AMEND2}


def test_발송번호는_하이픈이_있어도_찾는다():
    assert _cut(dispatch="9-5-2099-000000001").admin[-1].number == OA1


def test_청구항_이력을_모르면_보정서를_모두_보정_판으로_본다():
    cut = cut_at_oa(parse_admin_history(ADMIN), None, OA1)
    kinds = {e.doc_number_text: e.kind for e in cut.history}
    assert kinds[FORMAL] == "amendment" and cut.claim_changes == []


def test_머리글만_있으면_대상_OA_없음():
    got = cut_at_oa(parse_admin_history(ADMIN_HEAD), [], OA1)
    assert got == Missing(
        "admin_history", UnverifiedReason.LOOKUP_FAILED, "대상 OA가 행정 이력에 없음"
    )


def test_대상_OA가_두번이면_모호함():
    admin = admin_text([(OA1, "1", "의견제출통지서"), (OA1, "2", "의견제출통지서")])
    got = cut_at_oa(parse_admin_history(admin), [], OA1)
    assert isinstance(got, Missing) and got.reason == UnverifiedReason.AMBIGUOUS


def test_발송번호_꼴이_아니면_입력_확인_안됨():
    got = cut_at_oa(parse_admin_history(ADMIN), [], "없음")
    assert isinstance(got, Missing) and got.reason == UnverifiedReason.INPUT_UNVERIFIED


@pytest.mark.parametrize("text", ["", "출원번호¶접수발송일자\n1¶2"])
def test_칸이_빠진_표는_꼴_오류(text):
    with pytest.raises(SourceFormatError):
        parse_admin_history(text)


class FakeSource:
    name = "fake"

    def __init__(self, files: SourceFiles):
        self.files = files
        self.asked: list[tuple[str, str]] = []

    def fetch(self, application_number, dispatch_number):
        self.asked.append((application_number, dispatch_number))
        return self.files


def test_조회는_가져온_것을_자르고_없는_것은_이유와_함께():
    gone = Missing("application_document", UnverifiedReason.LOOKUP_FAILED, "출원서 파일 없음")
    source = FakeSource(SourceFiles(ADMIN, CLAIMS, gone))
    got = lookup_case(source, APP, OA1)
    assert source.asked == [(APP, OA1)]
    assert got.cut is not None and got.cut.admin[-1].number == OA1
    assert got.application_document is None and got.missing == [gone]


def test_못_읽은_표는_not_extracted로_남고_이력은_청구항_없이_자른다():
    source = FakeSource(SourceFiles(ADMIN, "깨진 글자", Path("x.pdf")))
    got = lookup_case(source, APP, OA1)
    assert [m.what for m in got.missing] == ["claim_history"]
    assert got.missing[0].reason == UnverifiedReason.NOT_EXTRACTED
    assert got.cut is not None and got.application_document == Path("x.pdf")


def test_이력을_못_가져오면_자른_것이_없다():
    gone = Missing("admin_history", UnverifiedReason.LOOKUP_FAILED, "없음")
    got = lookup_case(FakeSource(SourceFiles(gone, CLAIMS, Path("x.pdf"))), APP, OA1)
    assert got.cut is None and got.missing == [gone]
