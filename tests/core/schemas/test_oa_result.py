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
    build_oa_result,
    build_rejection,
    collect_evidence,
    summarize_rejection_status,
    summarize_status,
)

OK = Status(value="confirmed", checked="1쪽 글자와 일치")
BAD = Status(value="unverified", reason="ambiguous")
CONFLICT = Status(value="conflict")


def ev(value, raw="원문", page: int | None = 1, status: Status = OK):
    return {"value": value, "raw_text": raw, "page": page, "status": status}


def rej_fields(article="29-2", claims=(1, 2), supported=True, flags=(), **extra):
    data = {
        "article": article if isinstance(article, dict) else ev(article),
        "supported": supported,
        "claims": ev(list(claims)),
        "citations": [],
        "examiner_reasoning": ev("요지"),
        "flags": list(flags),
    }
    data.update(extra)
    return data


def rejection(*args, **kw):
    """status·evidence는 도우미가 칸에서 모아 채운다."""
    return build_rejection(document_id="d_1", **rej_fields(*args, **kw))


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
    return ExaminerHints(allowable_claims={**none_value, "value": []}, amendment_note=none_value)


def oa_fields(rejections, **extra):
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
    }
    data.update(extra)
    return data


def oa(rejections, **extra):
    return build_oa_result(document_id="d_1", **oa_fields(rejections, **extra))


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
    assert r.examiner_hints.amendment_note.value is None


def test_직렬화하면_status는_네_키():
    dumped = oa([rejection()]).model_dump(mode="json")
    assert set(dumped["status"]) == {"value", "reason", "checked", "searched_scope"}
    assert dumped["notice_kind"]["value"] == "initial"


def test_notice_kind_값은_셋():
    assert {k.value for k in NoticeKind} == {"initial", "final", "unknown"}


# ---------- 결과 전체 status 모으기 ----------


def cit(country="KR", supported=True, flags=(), country_status=OK, **extra):
    data = {
        "number": ev("KR10-0000001"),
        "country": ev(country, status=country_status),
        "country_supported": supported,
        "cited_paragraphs": ev(["0023"]),
        "flags": list(flags),
    }
    data.update(extra)
    return Citation(**data)


def bad_reasoning(status=BAD):
    return ev("요지", status=status)


def test_모두_confirmed면_모든_칸_원문_대조():
    s = oa([rejection()]).status
    assert s.value == StatusValue.CONFIRMED
    assert s.checked == "모든 칸 원문 대조"


def test_가장_나쁜_값을_모은다_충돌이_확인되지_않음보다_나쁨():
    r = oa(
        [
            rejection(examiner_reasoning=bad_reasoning()),
            rejection(examiner_reasoning=conflict_value()),
        ],
    )
    assert r.status.value == StatusValue.CONFLICT


def test_같은_등급이면_앞_칸의_reason_식별정보가_거절이유보다_앞():
    r = oa(
        [
            rejection(
                examiner_reasoning=bad_reasoning(Status(value="unverified", reason="body_missing"))
            )
        ],
        application_number=ev(None, None, None, Status(value="unverified", reason="lookup_failed")),
    )
    assert r.status.reason == UnverifiedReason.LOOKUP_FAILED


def test_지원_안_하는_거절이유의_칸은_모으지_않는다():
    unsupported = rejection(
        article="46",
        supported=False,
        flags=[Flag.NEEDS_HUMAN_REVIEW],
        examiner_reasoning=bad_reasoning(),
    )
    assert unsupported.status.value == StatusValue.UNVERIFIED  # 그 거절이유 자체는 나쁨
    r = oa([rejection(), unsupported])
    assert r.status.value == StatusValue.CONFIRMED  # 결과 전체는 flags로만 표시


def test_지원하는_거절이유가_나쁘면_결과도_나쁨():
    r = oa([rejection(), rejection(examiner_reasoning=bad_reasoning())])
    assert r.status.value == StatusValue.UNVERIFIED


def test_summarize는_칸만_받아_모은다():
    only = ("article", "claims", "citations", "examiner_reasoning")  # 이 네 칸만 받는다
    ok = {k: v for k, v in rej_fields().items() if k in only}
    assert summarize_rejection_status(**ok).value == StatusValue.CONFIRMED
    bad = {k: v for k, v in rej_fields(examiner_reasoning=bad_reasoning()).items() if k in only}
    assert summarize_rejection_status(**bad).value == StatusValue.UNVERIFIED
    assert summarize_status(**oa_fields([rejection()])).value == StatusValue.CONFIRMED


def test_지원_안_하는_나라_확인됨_인용문헌은_모으기에서_빠짐():
    jp = cit(
        "JP",
        supported=False,
        flags=[Flag.NEEDS_HUMAN_REVIEW],
        number=ev("JP 2000-1", status=BAD),
        cited_paragraphs=ev(["0001"], status=BAD),
    )
    assert rejection(citations=[jp]).status.value == StatusValue.CONFIRMED


def test_나라를_못_정한_인용문헌은_unverified가_거절이유_status에_늘_들어감():
    unknown = cit(
        None,
        supported=False,
        flags=[Flag.NEEDS_HUMAN_REVIEW],
        country_status=Status(value="unverified", reason="ambiguous"),
    )
    s = rejection(citations=[unknown]).status
    assert s.value == StatusValue.UNVERIFIED
    assert s.reason == UnverifiedReason.AMBIGUOUS


def test_KR_US는_supported_true_그_밖은_false():
    with pytest.raises(ValidationError):
        cit("JP", supported=True)
    with pytest.raises(ValidationError):
        cit("KR", supported=False, flags=[Flag.NEEDS_HUMAN_REVIEW])
    with pytest.raises(ValidationError):
        cit("US", supported=False, flags=[Flag.NEEDS_HUMAN_REVIEW])
    assert cit("US").country_supported is True


def test_나라_value가_null인데_country_status가_confirmed면_거부():
    with pytest.raises(ValidationError):
        cit(None, supported=False, flags=[Flag.NEEDS_HUMAN_REVIEW])


# ---------- 저장된 status와 모은 값의 일치 ----------


def test_거절이유_0개인데_confirmed인_OAResult는_거부():
    with pytest.raises(ValidationError):
        OAResult(**oa_fields([]), status=OK)


def test_Rejection_status가_안쪽_칸과_다르면_거부():
    with pytest.raises(ValidationError):
        Rejection(**rej_fields(examiner_reasoning=bad_reasoning()), status=OK)


def test_OAResult_status가_칸을_모은_값과_다르면_거부():
    bad_rej = rejection(examiner_reasoning=bad_reasoning())
    with pytest.raises(ValidationError):
        OAResult(**oa_fields([bad_rej]), status=OK)


# ---------- 결과 단위 evidence ----------


def test_쪽이_있는_값마다_document_id_page_raw_text를_모은다():
    r = oa([rejection(article="29-2")])
    assert r.evidence
    assert all(e.document_id == "d_1" and e.page is not None for e in r.evidence)
    # 쪽 없는 값(통지 종류 initial, 힌트 없음)은 들어가지 않음
    assert all(e.raw_text is not None for e in r.evidence)
    assert collect_evidence(r, "d_1") == r.evidence
    assert rejection().evidence  # 거절이유 하나도 같은 규칙


def test_evidence는_확인됨이고_쪽이_있는_값만():
    bad_claims = ev([1], raw="제1항", page=2, status=BAD)
    fields = rej_fields()
    fields["claims"] = bad_claims
    r = build_rejection(document_id="d_1", **fields)
    raws = [e.raw_text for e in r.evidence]
    assert "제1항" not in raws  # unverified 값은 대조에 통과하지 못함
    assert "원문" in raws  # confirmed + 쪽 있는 값은 들어감


def test_summarize는_모르는_필드_이름이면_TypeError():
    with pytest.raises(TypeError):
        summarize_rejection_status(
            article=ev("29-2"), claims=ev([1]), citations=[], examiner_reasoning=ev("x"), oops=1
        )


def test_build_rejection은_모르는_필드_이름이면_TypeError():
    with pytest.raises(TypeError):
        build_rejection(document_id="d_1", **rej_fields(), oops=1)


# ---------- 빈 입력 ----------


def test_거절이유_0개면_unverified_not_extracted와_경고(caplog):
    with caplog.at_level(logging.WARNING):
        s = oa([]).status
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
        cit("JP", supported=False)


def test_status_네_값_밖은_거부():
    with pytest.raises(ValidationError):
        OAResult(**oa_fields([rejection()]), status={"value": "maybe"})


def test_모르는_키는_조용히_버리지_않고_거부():
    with pytest.raises(ValidationError):
        OAResult(**oa_fields([rejection()]), status=OK, surprise=1)
    with pytest.raises(ValidationError):
        Status(value="conflict", surprise=1)
    with pytest.raises(ValidationError):
        CaseMaterials(case_id="c_1", surprise=1)


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


# ---------- 조문을 모르는 거절이유는 결과 status에 넣는다 (11/18 리뷰) ----------


def test_조문을_모르는_거절이유는_supported_false여도_결과_status에_들어감():
    unknown_article = rejection(
        supported=False,
        flags=[Flag.NEEDS_HUMAN_REVIEW],
        article=ev(None, None, None, BAD),
    )
    assert unknown_article.status.value == StatusValue.UNVERIFIED
    assert oa([rejection(), unknown_article]).status.value == StatusValue.UNVERIFIED


def test_조문이_충돌인_거절이유도_결과_status에_들어감():
    conflicted = build_rejection(
        document_id="d_1",
        **rej_fields(supported=False, flags=[Flag.NEEDS_HUMAN_REVIEW], article=conflict_value()),
    )
    assert oa([rejection(), conflicted]).status.value == StatusValue.CONFLICT


def test_거절이유_0개인데_위쪽_필드가_모두_input_unverified면_이유도_input_unverified(caplog):
    bad = ev(None, None, None, Status(value="unverified", reason="input_unverified"))
    kind = {**bad, "value": "unknown"}
    empty = {"value": [], "raw_text": None, "page": None, "status": bad["status"]}
    fields = oa_fields(
        [],
        application_number=bad,
        dispatch_number=bad,
        notice_date=bad,
        response_due=bad,
        notice_kind=kind,
        examiner_hints=ExaminerHints(allowable_claims=empty, amendment_note=bad),
    )
    with caplog.at_level(logging.WARNING):
        s = summarize_status(**fields)
    assert s.reason == UnverifiedReason.INPUT_UNVERIFIED
    assert not any("거절이유 0개" in r.getMessage() for r in caplog.records)
