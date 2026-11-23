"""지휘의 사건 채우기 단계 구현 (이슈 #54 task-4, DB 없이)."""

from patent_ai.core.cases.case_source.base import Missing
from patent_ai.core.cases.case_source.fill import FillOutcome
from patent_ai.core.cases.case_source.filler import SourceCaseFiller, describe_fill
from patent_ai.core.f3_claim_compare.inputs import F3Inputs
from patent_ai.core.schemas.common import Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.document import PageText

GONE = Missing("application_document", UnverifiedReason.LOOKUP_FAILED, "받아 둔 폴더에 출원서 없음")


def test_채운_것과_못_가져온_것과_글자_여부를_한_줄로():
    line = describe_fill("local_folder", FillOutcome(True, [GONE]), has_texts=False)
    assert line == (
        "local_folder로 채움 / 출원서 없음 (lookup_failed: 받아 둔 폴더에 출원서 없음)"
        " / OA 당시 청구항·명세서 글자를 못 만듦 (판 문서 없음 등, 서버 로그)"
    )


def test_건너뛴_이유를_남긴다():
    line = describe_fill("local_folder", FillOutcome(False, why="이미 채운 사건"), has_texts=True)
    assert line == "채우지 않음: 이미 채운 사건"


class _Fill:
    def __init__(self, out):
        self.out, self.calls = out, []

    def fill_before_f3(self, oa_id, application_number, dispatch_number):
        self.calls.append((oa_id, application_number, dispatch_number))
        return self.out


class _Texts:
    def __init__(self, value):
        self.value = value

    def texts_for(self, oa_id):
        return self.value


def test_이미_채운_사건이어도_글자는_다시_만든다():
    fill = _Fill(FillOutcome(False, why="이미 채운 사건"))
    ok = Status(value=StatusValue.CONFIRMED, checked="가짜")
    texts = F3Inputs(
        claims_at_oa={1: "가 장치."},
        claims_status=ok,
        claims_document_id="doc_spec",
        spec=PageText(document_id="doc_spec", pages=[], status=ok),
    )
    got = SourceCaseFiller(fill, _Texts(texts), "local_folder").fill("oa_1", "a", "d")
    assert fill.calls == [("oa_1", "a", "d")]
    assert got.texts == texts and got.reason == "채우지 않음: 이미 채운 사건"
