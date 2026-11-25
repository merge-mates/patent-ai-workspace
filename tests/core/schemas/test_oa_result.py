"""OAResult·CaseMaterials 테스트. 기대값은 tasks.md m1-i2-14 task-2, design.md 3-2절."""

import logging

import pytest
from pydantic import ValidationError

from patent_ai.core.schemas.case_materials import CaseMaterials
from patent_ai.core.schemas.common import Flag, Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.oa_result import (
    Citation,
    ClaimRow,
    ExaminerHints,
    NoticeKind,
    OAResult,
    Rejection,
    RejectionKind,
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
        "no": 1,
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
        "examined_claims": ev([1, 2, 3, 4, 5, 6, 7], "제1항 내지 제7항"),
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
        "label": "D1",
        "number": ev("KR20990000001A"),
        "country": ev(country, status=country_status),
        "country_supported": supported,
        "cited_paragraphs": ev(["[0023]"]),
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
        documents=[
            {
                "document_id": "d_1",
                "kind": "oa",
                "source": "uploaded",
                "status": {"value": "confirmed", "checked": "출원번호·문서번호 확인"},
            }
        ],
        missing=[missing()],
        held_tasks=[{"task": "F3", "waiting_for": "인용문헌 본문"}],
        review_items=[_item("a"), _item("b")],
        review_items_count=2,
    )
    assert m.missing[0].ask_upload is True
    assert m.held_tasks[0].task == "F3"
    assert m.review_items_count == 2


def _item(label: str) -> dict:
    return {"kind": "unverified", "target": f"t.{label}", "label": label, "reason": "r"}


def test_검토할_사항_줄_수와_개수가_같으면_통과():
    m = CaseMaterials(case_id="c_1", review_items=[_item("a"), _item("b")], review_items_count=2)
    assert len(m.review_items) == m.review_items_count == 2


def test_검토할_사항_빈_목록과_개수_0은_통과():
    m = CaseMaterials(case_id="c_1", review_items=[], review_items_count=0)
    assert m.review_items == [] and m.review_items_count == 0


def test_검토할_사항_줄_2개에_개수_3이면_거부():
    with pytest.raises(ValidationError):
        CaseMaterials(case_id="c_1", review_items=[_item("a"), _item("b")], review_items_count=3)


def test_검토할_사항_목록이_없는데_개수가_있으면_거부():
    # 목록 None = 마무리 안 한 ⑥. 개수만 있으면 줄이 없는 개수라 거부
    with pytest.raises(ValidationError):
        CaseMaterials(case_id="c_1", review_items=None, review_items_count=2)


def test_문서에_글자_추출_상태_칸이_있고_기본은_None():
    doc = {
        "document_id": "d_1",
        "kind": "oa",
        "source": "uploaded",
        "status": {"value": "confirmed", "checked": "x"},
    }
    assert CaseMaterials(case_id="c_1", documents=[doc]).documents[0].text_status is None
    doc["text_status"] = {"value": "unverified", "reason": "body_missing"}
    got = CaseMaterials(case_id="c_1", documents=[doc]).documents[0]
    assert got.text_status.reason == "body_missing"


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
        examined_claims=ev(None, None, None, Status(value="unverified", reason="input_unverified")),
        examiner_hints=ExaminerHints(allowable_claims=empty, amendment_note=bad),
    )
    with caplog.at_level(logging.WARNING):
        s = summarize_status(**fields)
    assert s.reason == UnverifiedReason.INPUT_UNVERIFIED
    assert not any("거절이유 0개" in r.getMessage() for r in caplog.records)


# ---------- #18: 정답 형식에 맞춘 칸 ----------


def test_OAResult에_심사_대상_청구항_칸이_있고_직렬화에_나온다():
    dumped = oa([rejection()]).model_dump(mode="json")
    assert dumped["examined_claims"]["value"] == [1, 2, 3, 4, 5, 6, 7]


def test_심사_대상_청구항이_확인되지_않으면_결과도_확인되지_않음():
    bad = ev(None, None, None, Status(value="unverified", reason="not_extracted"))
    r = oa([rejection()], examined_claims=bad)
    assert r.status.value == StatusValue.UNVERIFIED


def test_심사_대상_청구항이_확인됨이면_결과_evidence에_든다():
    raws = [e.raw_text for e in oa([rejection()]).evidence]
    assert "제1항 내지 제7항" in raws


def test_거절이유는_순번_인용문헌은_라벨이_필수():
    fields = rej_fields()
    del fields["no"]
    with pytest.raises(ValueError):
        build_rejection(document_id="d_1", **fields)
    data = cit().model_dump()
    del data["label"]
    with pytest.raises(ValueError):
        Citation(**data)


def test_순번과_라벨_값이_그대로_직렬화된다():
    r = rejection(citations=[cit(label="D2")], no=3)
    assert r.no == 3
    assert r.citations[0].label == "D2"


# ---------- #18 task-5: 거절이유 종류 kind (조문 코드에서 규칙으로 정함) ----------


def test_RejectionKind_값은_넷():
    assert {k.value for k in RejectionKind} == {"novelty", "inventive_step", "clarity", "other"}


@pytest.mark.parametrize(
    ("article", "kind"),
    [
        ("29-1-1", "novelty"),
        ("29-1-2", "novelty"),
        ("29-2", "inventive_step"),
        ("42-4-2", "clarity"),
        ("42-3", "other"),
        ("42-8", "other"),
        ("29-1", "other"),  # 호 없는 29조 1항은 지원 표 밖
    ],
)
def test_조문_코드마다_kind가_정해진다(article, kind):
    supported = article in {"29-1-1", "29-1-2", "29-2", "42-4-2"}
    flags = [] if supported else [Flag.NEEDS_HUMAN_REVIEW]
    r = rejection(article, supported=supported, flags=flags)
    assert r.kind == kind
    assert r.model_dump(mode="json")["kind"] == kind  # 직렬화는 영어 코드 문자열


def test_호가_여럿이면_모두_신규성이면_novelty():
    r = rejection("29-1-1|29-1-2")
    assert r.kind == RejectionKind.NOVELTY and r.supported


def test_호가_여럿이어도_종류가_섞이면_other():
    r = rejection("29-1-1|42-4-2", supported=False, flags=[Flag.NEEDS_HUMAN_REVIEW])
    assert r.kind == RejectionKind.OTHER


def test_조문을_모르면_other이고_supported_flags_status_규칙은_그대로():
    r = rejection(
        supported=False, flags=[Flag.NEEDS_HUMAN_REVIEW], article=ev(None, None, None, BAD)
    )
    assert r.kind == RejectionKind.OTHER
    assert r.status.value == StatusValue.UNVERIFIED  # 조문 모름은 status를 나쁘게 함
    assert oa([rejection(), r]).status.value == StatusValue.UNVERIFIED


def test_조문이_충돌이면_other():
    r = build_rejection(
        document_id="d_1",
        **rej_fields(supported=False, flags=[Flag.NEEDS_HUMAN_REVIEW], article=conflict_value()),
    )
    assert r.kind == RejectionKind.OTHER and r.status.value == StatusValue.CONFLICT


def test_kind를_사람이_넣을_수_없다():
    with pytest.raises(TypeError):
        build_rejection(document_id="d_1", **rej_fields(), kind="clarity")


def test_조문과_안_맞는_kind는_거부():
    data = rejection("29-2").model_dump(mode="json")
    data["kind"] = "clarity"
    with pytest.raises(ValidationError):
        Rejection.model_validate(data)


def test_kind_없는_거절이유는_거부():
    data = rejection().model_dump(mode="json")
    del data["kind"]
    with pytest.raises(ValidationError):
        Rejection.model_validate(data)


# ---------- #18 task-6: 청구항 줄 ClaimRow, OAResult.claim_rows ----------


def row_fields(**extra):
    data = {
        "claim": 1,
        "rejection": 1,
        "citations": ["D1"],
        "locations": {"D1": ["[0014]", "도 4b"]},
        "same_as": [],
        "clarity_terms": [],
        "clarity_reason": None,
        "raw_text": "청구항 1은 인용발명 1의 [0014]에 개시",
        "page": 3,
        "status": OK,
    }
    data.update(extra)
    return data


NOT_EXTRACTED = Status(value="unverified", reason="not_extracted")


def unverified_row(**extra):
    return row_fields(
        citations=[], locations={}, raw_text=None, page=None, status=NOT_EXTRACTED, **extra
    )


def test_청구항_줄은_정답_형식_칸을_가진다():
    row = ClaimRow(**row_fields(same_as=["claim:1", "rejection:2"]))
    dumped = row.model_dump(mode="json")
    assert set(dumped) == {
        "check_failed",  # 11/26 D3: 대조에 떨어진 줄의 떨어진 검사
        "claim",
        "rejection",
        "citations",
        "locations",
        "same_as",
        "clarity_terms",
        "clarity_reason",
        "clarity_reason_origin",
        "no_location",
        "raw_text",
        "page",
        "status",
    }
    assert dumped["locations"] == {"D1": ["[0014]", "도 4b"]}


def test_확인되지_않은_줄은_값이_비어_있고_쪽과_글자가_없다():
    row = ClaimRow(**unverified_row())
    assert row.status.value == StatusValue.UNVERIFIED and row.page is None


@pytest.mark.parametrize(
    "bad",
    [
        {"locations": {"D9": ["[0014]"]}},  # 인용에 없는 라벨
        {"same_as": ["claim:x"]},  # 같은 취지 꼴
        {"same_as": ["청구항 1"]},
        {"raw_text": None, "page": None},  # confirmed인데 근거 없음
        {"claim": None},  # confirmed인데 청구항 번호 없음
        {"rejection": None},
        {"page": 3, "raw_text": "  "},  # 쪽이 있으면 글자도
    ],
)
def test_확인됨_줄의_모양이_틀리면_거부(bad):
    with pytest.raises(ValidationError):
        ClaimRow(**row_fields(**bad))


@pytest.mark.parametrize(
    "bad",
    [
        {"citations": ["D1"]},
        {"locations": {"D1": ["[0014]"]}, "citations": ["D1"]},
        {"same_as": ["claim:1"]},
        {"clarity_terms": ["약"]},
        {"raw_text": "원문", "page": 1},
    ],
)
def test_확인되지_않은_줄에_값을_남기면_거부(bad):
    data = unverified_row()
    data.update(bad)
    with pytest.raises(ValidationError):
        ClaimRow(**data)


def test_OAResult에_청구항_줄이_들어가고_직렬화에_나온다():
    r = oa([rejection("29-2", [1, 2])], claim_rows=[row_fields(), row_fields(claim=2)])
    assert [row.claim for row in r.claim_rows] == [1, 2]
    assert r.model_dump(mode="json")["claim_rows"][0]["rejection"] == 1
    assert oa([rejection()]).claim_rows == []  # 없으면 빈 목록


def test_줄이_가리키는_거절이유가_없으면_거부():
    with pytest.raises(ValueError):
        oa([rejection()], claim_rows=[row_fields(rejection=2)])


def test_지원_안_하는_거절이유의_줄은_거부():
    unsupported = rejection("42-3", supported=False, flags=[Flag.NEEDS_HUMAN_REVIEW])
    with pytest.raises(ValueError):
        oa([unsupported], claim_rows=[row_fields()])


def test_명확성이_아닌_줄에_명확성_표현이_있으면_거부():
    with pytest.raises(ValueError):
        oa(
            [rejection("29-2")],
            claim_rows=[
                row_fields(
                    clarity_terms=["약"], clarity_reason="x", clarity_reason_origin="ai_generated"
                )
            ],
        )


def test_명확성_줄은_인용과_위치_대신_표현을_가진다():
    clarity = rejection("42-4-2", [1])
    good = row_fields(
        citations=[],
        locations={},
        clarity_terms=["상기 프리뷰 이미지"],
        clarity_reason="앞에 정의 없음",
        clarity_reason_origin="ai_generated",
    )
    assert oa([clarity], claim_rows=[good]).claim_rows[0].clarity_terms == ["상기 프리뷰 이미지"]
    with pytest.raises(ValueError):  # 명확성 줄에 인용이 있으면 거부
        oa([clarity], claim_rows=[row_fields(clarity_terms=["약"])])


def test_확인되지_않은_줄이_있으면_결과도_확인되지_않음():
    r = oa([rejection("29-2", [1, 2])], claim_rows=[row_fields(), unverified_row(claim=2)])
    assert r.status.value == StatusValue.UNVERIFIED
    assert r.status.reason == UnverifiedReason.NOT_EXTRACTED


def test_확인됨_줄은_결과_status를_안_바꾸고_evidence에_든다():
    r = oa([rejection()], claim_rows=[row_fields()])
    assert r.status.value == StatusValue.CONFIRMED
    assert "청구항 1은 인용발명 1의 [0014]에 개시" in [e.raw_text for e in r.evidence]
    assert any(e.page == 3 for e in r.evidence)


def test_summarize는_claim_rows를_받아_모은다():
    base = oa_fields([rejection()])
    base.pop("oa_id")
    ok = summarize_status(**base, claim_rows=[ClaimRow(**row_fields())])
    bad = summarize_status(**base, claim_rows=[ClaimRow(**unverified_row())])
    assert ok.value == StatusValue.CONFIRMED and bad.value == StatusValue.UNVERIFIED


def test_명확성_이유가_있으면_AI가_쓴_글_표시가_꼭_있고_없으면_표시도_없다():
    base = row_fields(citations=[], locations={}, clarity_reason="앞에 정의 없음")
    with pytest.raises(ValidationError):
        ClaimRow(**base)  # 이유는 AI가 쓴 글인데 표시 없음
    with pytest.raises(ValidationError):
        ClaimRow(**row_fields(clarity_reason_origin="ai_generated"))  # 이유 없는데 표시만
    with pytest.raises(ValidationError):
        ClaimRow(**{**base, "clarity_reason_origin": "human_edited"})
    assert ClaimRow(**{**base, "clarity_reason_origin": "ai_generated"}).clarity_reason


def test_애매한_확인되지_않음_줄은_값과_원문_쪽을_남길_수_있다():
    ambiguous = Status(value="unverified", reason="ambiguous")
    row = ClaimRow(**row_fields(status=ambiguous))
    assert row.citations == ["D1"] and row.page == 3
    r = oa([rejection("29-2", [1, 2])], claim_rows=[row_fields(status=ambiguous)])
    assert (
        r.status.value == StatusValue.UNVERIFIED and r.status.reason == UnverifiedReason.AMBIGUOUS
    )


def test_애매가_아닌_확인되지_않음_줄은_여전히_값을_못_남긴다():
    with pytest.raises(ValidationError):
        ClaimRow(**row_fields(status=NOT_EXTRACTED))
    with pytest.raises(ValidationError):  # 애매여도 번호는 있어야 어느 줄인지 안다
        ClaimRow(**row_fields(claim=None, status=Status(value="unverified", reason="ambiguous")))


# ---------- #18 task-7: 인용 없는 줄의 no_location ----------
NO_LOC = "위치 없음 (설계 사항)"


def test_인용_없는_줄은_no_location을_가질_수_있다():
    row = ClaimRow(**row_fields(citations=[], locations={}, no_location=NO_LOC))
    assert row.model_dump(mode="json")["no_location"] == NO_LOC
    assert ClaimRow(**row_fields()).no_location is None  # 기본은 null


@pytest.mark.parametrize(
    "bad",
    [
        {"locations": {"D1": ["[0014]"]}},  # 위치와 같이
        {"citations": [], "locations": {}, "clarity_terms": ["약"]},  # 명확성 표현과 같이
        {"citations": [], "locations": {}, "no_location": "설계 사항"},  # 꼴이 틀림
        {"citations": [], "locations": {}, "no_location": "위치 없음 ()"},
    ],
)
def test_no_location이_위치_명확성_표현과_같이_있거나_꼴이_틀리면_거부(bad):
    data = row_fields(citations=[], locations={}, no_location=NO_LOC)
    data.update(bad)
    with pytest.raises(ValidationError):
        ClaimRow(**data)


def test_애매가_아닌_확인되지_않음_줄은_no_location도_못_남긴다():
    with pytest.raises(ValidationError):
        ClaimRow(**{**unverified_row(), "no_location": NO_LOC})
