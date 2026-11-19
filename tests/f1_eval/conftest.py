"""F1 채점 테스트 공용: tests/fixtures/f1_eval/gold_ok.json과 같은 내용의 OAResult를 만든다.

값은 모두 지어낸 것. #112의 build_oa_result로 만들어 진짜 결과 모양 검사를 통과한다.
"""

import pytest

from patent_ai.core.schemas.common import ExtractedValue, Flag, Origin, Status, StatusValue
from patent_ai.core.schemas.oa_result import (
    Citation,
    ClaimRow,
    ExaminerHints,
    OAResult,
    build_oa_result,
)

OK = Status(value=StatusValue.CONFIRMED, checked="원문 대조")
AMBIGUOUS = Status(value=StatusValue.UNVERIFIED, reason="ambiguous")


def ev(value=None, raw=None, page=None, status=OK) -> ExtractedValue:
    return ExtractedValue(value=value, raw_text=raw, page=page, status=status)


def _citation(label, key, raw, country) -> Citation:
    return Citation(
        label=label,
        number=ev(key, raw, 2),
        country=ev(country),
        country_supported=True,
        cited_paragraphs=ev([]),
    )


D1 = ("D1", "KR20990000001A", "공개특허공보 제10-2099-0000001호(2099.12.23.)", "KR")
D2 = ("D2", "US1234567B2", "미국 등록특허공보 US 1,234,567 B2", "US")


def _row(claim, rejection, page, raw, **kw) -> ClaimRow:
    return ClaimRow(claim=claim, rejection=rejection, page=page, raw_text=raw, status=OK, **kw)


def build_oa(**over) -> OAResult:
    """gold_ok.json과 같은 OA. over로 칸 하나를 바꿔 끼운다 (예: claim_rows=[...])."""
    fields = dict(
        oa_id="oa-1",
        application_number=ev("1020990000001", "10-2099-0000001", 1),
        dispatch_number=ev("952099000000001", "9-5-2099-000000001", 1),
        notice_date=ev(None, "2099.01.26.", 1),
        response_due=ev(None, "2099.03.26.", 1),
        notice_kind=ev("initial"),
        examined_claims=ev([1, 2, 3], "제1-3항", 1),
        examiner_hints=ExaminerHints(allowable_claims=ev([]), amendment_note=ev(None)),
        rejections=[
            dict(
                no=1,
                article=ev("29-2", "특허법 제29조제2항", 1),
                supported=True,
                claims=ev([1, 2, 3], "청구항 제1항 내지 제3항", 1),
                citations=[_citation(*D1), _citation(*D2)],
                examiner_reasoning=ev("요지"),
            ),
            dict(
                no=2,
                article=ev("42-4-2", "특허법 제42조제4항제2호", 1),
                supported=True,
                claims=ev([2], "청구항 제2항", 1),
                citations=[],
                examiner_reasoning=ev("요지"),
            ),
            dict(
                no=3,
                article=ev("42-3-1", "특허법 제42조제3항제1호", 1),
                supported=False,
                claims=ev([], "발명의 설명", 1),
                citations=[],
                examiner_reasoning=ev("요지"),
                flags=[Flag.NEEDS_HUMAN_REVIEW],
            ),
        ],
        claim_rows=[
            _row(
                1,
                1,
                3,
                "청구항 1은 D1, D2로 쉽게",
                citations=["D1", "D2"],
                locations={
                    "D1": ["[0014]", "[0080]-[0081]", "도 4b"],
                    "D2": ["청구항 1", "3:5-10"],
                },
            ),
            _row(
                2,
                1,
                3,
                "청구항 2는 단순 부가",
                citations=["D1"],
                locations={"D1": ["위치 없음 (단순 부가)"]},
            ),
            _row(3, 1, 3, "청구항 3은 청구항 1과 같은 취지", citations=["D1"], same_as=["claim:1"]),
            _row(
                2,
                2,
                4,
                "상기 프리뷰 이미지는 앞에 정의 없음",
                clarity_terms=["상기 프리뷰 이미지"],
                clarity_reason="앞에 정의 없음",
                clarity_reason_origin=Origin.AI_GENERATED,
            ),
        ],
    )
    fields.update(over)
    return build_oa_result(document_id="doc-1", **fields)


PAGE1 = "\n".join(
    [
        "출원번호 10-2099-0000001  발송번호 9-5-2099-000000001",
        "발송일자 2099.01.26.  제출기일 2099.03.26.",
        "심사 대상 제1-3항",
        "1 청구항 제1항 내지 제3항 특허법 제29조제2항",
        "2 청구항 제2항 특허법 제42조제4항제2호",
        "3 발명의 설명 특허법 제42조제3항제1호",
    ]
)
PAGE2 = "공개특허공보 제10-2099-0000001호(2099.12.23.)\n미국 등록특허공보 US 1,234,567 B2"
PAGE3 = "청구항 1은 D1, D2로 쉽게 … 청구항 2는 단순 부가 … 청구항 3은 청구항 1과 같은 취지"
PAGE4 = "상기 프리뷰 이미지는 앞에 정의 없음"
PAGES = [PAGE1, PAGE2, PAGE3, PAGE4]


@pytest.fixture
def make_oa():
    return build_oa
