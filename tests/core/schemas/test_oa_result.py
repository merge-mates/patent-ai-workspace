"""OAResult·CaseMaterials 테스트. 기대값은 tasks.md m1-i2-14 task-2, design.md 3-2절."""

import logging

import pytest
from pydantic import ValidationError

from patent_ai.core.schemas.case_materials import CaseMaterials
from patent_ai.core.schemas.common import Flag, Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.oa_result import (
    Citation,
    ExaminerHints,
    NoticeKind,
    OAResult,
    Rejection,
    summarize_rejection_status,
    summarize_status,
)

OK = Status(value="confirmed", checked="1쪽 글자와 일치")
BAD = Status(value="unverified", reason="ambiguous")
CONFLICT = Status(value="conflict")


def ev(value, raw="원문", page: int | None = 1, status: Status = OK):
    return {"value": value, "raw_text": raw, "page": page, "status": status}


def rejection(article="29-2", claims=(1, 2), supported=True, flags=(), status=OK, **extra):
    data = {
        "article": ev(article),
        "supported": supported,
        "claims": ev(list(claims)),
        "citations": [],
        "examiner_reasoning": ev("요지"),
        "status": status,
        "flags": list(flags),
    }
    data.update(extra)
    return Rejection(**data)


def conflict_value():
    cands = [
        {"value": v, "raw_text": v, "page": 1, "source": s}
        for v, s in (("a", "rule"), ("b", "model"))
    ]
    return {"value": None, "raw_text": None, "page": None, "status": CONFLICT, "candidates": cands}


def hints():
    none_value = {
        "value": None,
        "raw_text": None,
        "page": None,
        "status": Status(value="confirmed", checked="원문에 칸 없음"),
    }
    return ExaminerHints(allowable_claims={**none_value, "value": []}, amendment_notes=none_value)


def oa(rejections, **extra):
    data = {
        "oa_id": "oa_1",
        "application_number": ev("10-2099-0000001"),
        "dispatch_number": ev("9-5-2099-000000001"),
        "notice_date": ev(None, "2099.01.26"),
        "response_due": ev(None, "2099.03.26"),
        "notice_kind": {
            "value": "initial",
            "raw_text": None,
            "page": None,
            "status": Status(value="confirmed", checked="최후 표시 없음, 1쪽 머리말을 봄"),
        },
        "examiner_hints": hints(),
        "rejections": rejections,
        "status": OK,
    }
    data.update(extra)
    return OAResult(**data)


# ---------- 평소 ----------


def test_청구항_1이_거절이유_둘에_들어간_결과():
    r = oa([rejection("29-2", [1, 2, 3, 4]), rejection("42-4-2", [1])])
    assert r.rejections[0].claims.value == [1, 2, 3, 4]
    assert r.rejections[1].claims.value == [1]  # 합치지 않고 거절이유마다 따로
    assert r.examined_claim_version is None  # F1은 채우지 않음


def test_쪽_없는_confirmed_값_통지종류_initial과_힌트_없음():
    r = oa([rejection()])
    assert r.notice_kind.value == NoticeKind.INITIAL
    assert r.notice_kind.page is None
    assert r.examiner_hints.allowable_claims.value == []
    assert r.examiner_hints.amendment_notes.value is None


def test_직렬화하면_status는_네_키():
    dumped = oa([rejection()]).model_dump(mode="json")
    assert set(dumped["status"]) == {"value", "reason", "checked", "searched_scope"}
    assert dumped["notice_kind"]["value"] == "initial"


def test_notice_kind_값은_셋():
    assert {k.value for k in NoticeKind} == {"initial", "final", "unknown"}


# ---------- 결과 전체 status 모으기 ----------


def test_모두_confirmed면_모든_칸_원문_대조():
    s = summarize_status(oa([rejection()]))
    assert s.value == StatusValue.CONFIRMED
    assert s.checked == "모든 칸 원문 대조"


def test_가장_나쁜_값을_모은다_충돌이_확인되지_않음보다_나쁨():
    r = oa(
        [
            rejection(examiner_reasoning=ev("요지", status=BAD)),
            rejection(examiner_reasoning=conflict_value()),
        ],
    )
    assert summarize_status(r).value == StatusValue.CONFLICT


def test_같은_등급이면_앞_칸의_reason_식별정보가_거절이유보다_앞():
    r = oa(
        [
            rejection(
                examiner_reasoning=ev(
                    "요지", status=Status(value="unverified", reason="body_missing")
                )
            )
        ],
        application_number=ev(None, None, None, Status(value="unverified", reason="lookup_failed")),
    )
    s = summarize_status(r)
    assert s.reason == UnverifiedReason.LOOKUP_FAILED


def test_지원_안_하는_거절이유의_칸은_모으지_않는다():
    unsupported = rejection(
        article="46",
        supported=False,
        flags=[Flag.NEEDS_HUMAN_REVIEW],
        status=BAD,
    )
    r = oa([rejection(), unsupported])
    assert summarize_status(r).value == StatusValue.CONFIRMED  # flags로만 표시


def test_지원하는_거절이유가_나쁘면_결과도_나쁨():
    r = oa([rejection(), rejection(examiner_reasoning=ev("요지", status=BAD))])
    assert summarize_status(r).value == StatusValue.UNVERIFIED


def test_거절이유_status도_같은_규칙으로_안_칸을_모은다():
    rej = rejection(examiner_reasoning=ev("요지", status=BAD))
    assert summarize_rejection_status(rej).value == StatusValue.UNVERIFIED
    assert summarize_rejection_status(rejection()).value == StatusValue.CONFIRMED


def test_지원_안_하는_나라_인용문헌은_거절이유_status를_나쁘게_하지_않음():
    cit = Citation(
        number=ev("JP 2000-1", status=BAD),
        country="JP",
        country_supported=False,
        cited_paragraphs=ev(["0001"], status=BAD),
        flags=[Flag.NEEDS_HUMAN_REVIEW],
    )
    rej = rejection(citations=[cit])
    assert summarize_rejection_status(rej).value == StatusValue.CONFIRMED


# ---------- 빈 입력 ----------


def test_거절이유_0개면_unverified_not_extracted와_경고(caplog):
    with caplog.at_level(logging.WARNING):
        s = summarize_status(oa([]))
    assert s.value == StatusValue.UNVERIFIED
    assert s.reason == UnverifiedReason.NOT_EXTRACTED
    assert caplog.records


# ---------- 실패 ----------


def test_notice_kind_unknown인데_confirmed면_거부():
    with pytest.raises(ValidationError):
        oa([rejection()], notice_kind=ev("unknown", None, None, OK))


def test_notice_kind_unknown은_unverified면_통과():
    r = oa(
        [rejection()],
        notice_kind=ev("unknown", None, None, Status(value="unverified", reason="not_extracted")),
    )
    assert r.notice_kind.value == NoticeKind.UNKNOWN


@pytest.mark.parametrize("name", ["notice_date", "response_due"])
def test_날짜_칸에_value를_넣으면_거부(name):
    with pytest.raises(ValidationError):
        oa([rejection()], **{name: ev("2099-01-26", "2099.01.26")})


def test_supported_false인데_needs_human_review_없으면_거부():
    with pytest.raises(ValidationError):
        rejection(article="46", supported=False)


def test_supported_false와_needs_human_review가_같이_있으면_통과():
    assert (
        rejection(article="46", supported=False, flags=[Flag.NEEDS_HUMAN_REVIEW]).supported is False
    )


def test_country_supported_false인데_needs_human_review_없으면_거부():
    with pytest.raises(ValidationError):
        Citation(
            number=ev("JP 2000-1"),
            country="JP",
            country_supported=False,
            cited_paragraphs=ev([]),
        )


def test_status_네_값_밖은_거부():
    with pytest.raises(ValidationError):
        oa([rejection()], status={"value": "maybe"})


# ---------- CaseMaterials ----------


def missing(**extra):
    data = {
        "what": "인용문헌 US 2099/0000001 본문",
        "depends_on_tasks": ["F3"],
        "lookup_result": "body_missing",
        "ask_upload": True,
    }
    data.update(extra)
    return data


def test_사건_자료_빠진_자료와_보류():
    m = CaseMaterials(
        case_id="c_1",
        documents=[{"document_id": "d_1", "kind": "oa", "source": "uploaded"}],
        missing=[missing()],
        held_tasks=[{"task": "F3", "waiting_for": "인용문헌 본문"}],
        review_items_count=2,
    )
    assert m.missing[0].ask_upload is True
    assert m.held_tasks[0].task == "F3"
    assert m.review_items_count == 2


def test_지원_안_하는_나라인데_ask_upload_true면_거부():
    with pytest.raises(ValidationError):
        CaseMaterials(
            case_id="c_1",
            missing=[missing(lookup_result="unsupported_country", ask_upload=True)],
        )


def test_지원_안_하는_나라는_ask_upload_false면_통과():
    m = CaseMaterials(
        case_id="c_1",
        missing=[missing(lookup_result="unsupported_country", ask_upload=False)],
    )
    assert m.missing[0].ask_upload is False


def test_조회_결과_세_값_밖은_거부():
    with pytest.raises(ValidationError):
        CaseMaterials(case_id="c_1", missing=[missing(lookup_result="whatever")])
