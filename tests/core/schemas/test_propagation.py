import logging

import pytest
from pydantic import ValidationError

from patent_ai.core.schemas.case_materials import CaseMaterials, LookupResult, MissingMaterial
from patent_ai.core.schemas.common import (
    Flag,
    ResultBase,
    Status,
    StatusValue,
    UnverifiedReason,
)
from patent_ai.core.schemas.oa_result import ExaminerHints, build_oa_result, build_rejection
from patent_ai.core.schemas.propagation import (
    ReviewItem,
    collect_review_items,
    mark_recheck,
    propagate,
)

OK = Status(value=StatusValue.CONFIRMED, checked="OA 본문 확인")
UNV = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.BODY_MISSING)
CONFLICT = Status(value=StatusValue.CONFLICT)
NOT_FOUND = Status(value=StatusValue.NOT_FOUND_IN_SCOPE, searched_scope="국내 공보")


def _empty_materials() -> CaseMaterials:
    return CaseMaterials(case_id="c1")


def test_propagate_모두_확인되면_확인됨():
    s = propagate([OK, OK])
    assert s.value == StatusValue.CONFIRMED
    assert "2" in s.checked  # "기대는 입력 2개 확인됨"


def test_propagate_하나라도_확인_안_되면_input_unverified():
    s = propagate([OK, UNV])
    assert s.value == StatusValue.UNVERIFIED
    assert s.reason == UnverifiedReason.INPUT_UNVERIFIED


@pytest.mark.parametrize("bad", [NOT_FOUND, CONFLICT])
def test_propagate_확인됨이_아니면_전부_input_unverified(bad):
    assert propagate([OK, bad]).reason == UnverifiedReason.INPUT_UNVERIFIED


def test_propagate_빈_목록은_기대는_입력_없음_영향_없음():
    assert propagate([]).value == StatusValue.CONFIRMED


def test_mark_recheck는_status를_바꾸지_않고_새_값을_돌려줌():
    r = ResultBase(status=OK)
    new = mark_recheck(r, "앞 입력이 바뀜")
    assert new.needs_recheck is True
    assert new.recheck_reason == "앞 입력이 바뀜"
    assert new.status == OK
    assert r.needs_recheck is False  # 원본은 그대로


def test_앞_결과가_unverified면_검토할_사항에_뜸():
    items = collect_review_items([ResultBase(status=UNV)], _empty_materials())
    assert [i.kind for i in items] == ["unverified"]
    assert "body_missing" in items[0].reason


def test_빠진_자료가_검토할_사항에_뜸():
    m = CaseMaterials(
        case_id="c1",
        missing=[
            MissingMaterial(
                what="인용문헌 2",
                depends_on_tasks=["comparison"],
                lookup_result=LookupResult.BODY_MISSING,
                ask_upload=True,
            )
        ],
    )
    items = collect_review_items([ResultBase(status=OK)], m)
    assert items == [
        ReviewItem(
            kind="missing_material",
            target="materials.missing[0]",
            label="인용문헌 2",
            reason="body_missing",
        )
    ]


def test_충돌_재확인_사람_검토_표시가_각각_뜸():
    r_flags = ResultBase(status=OK, flags=[Flag.NEEDS_HUMAN_JUDGMENT, Flag.NEEDS_HUMAN_REVIEW])
    r_recheck = mark_recheck(ResultBase(status=OK), "다시 확인")
    r_conflict = ResultBase(status=CONFLICT)
    kinds = [
        i.kind for i in collect_review_items([r_flags, r_recheck, r_conflict], _empty_materials())
    ]
    assert kinds == ["needs_human_judgment", "needs_human_review", "needs_recheck", "conflict"]


def test_조회_범위_내_없음은_검토할_사항이_아님():
    assert collect_review_items([ResultBase(status=NOT_FOUND)], _empty_materials()) == []


def test_결과_0개면_빈_목록과_경고(caplog):
    with caplog.at_level(logging.WARNING):
        assert collect_review_items([], _empty_materials()) == []
    assert caplog.records


def test_결과_0개여도_빠진_자료_줄은_남고_경고도_남음(caplog):
    m = CaseMaterials(
        case_id="c1",
        missing=[
            MissingMaterial(
                what="인용문헌 2",
                lookup_result=LookupResult.BODY_MISSING,
                ask_upload=True,
            )
        ],
    )
    with caplog.at_level(logging.WARNING):
        items = collect_review_items([], m)
    assert [i.kind for i in items] == ["missing_material"]
    assert caplog.records


def test_ReviewItem은_모르는_칸을_거부():
    with pytest.raises(ValidationError):
        ReviewItem(kind="unverified", target="t", label="l", reason="r", extra="x")


def test_결과는_있는데_검토할_사항_0건이면_경고_없음(caplog):
    with caplog.at_level(logging.WARNING):
        assert collect_review_items([ResultBase(status=OK)], _empty_materials()) == []
    assert not caplog.records


# ---------- 실제 OAResult 안쪽까지 ----------


def _ev(value, raw="원문", status=OK):
    return {"value": value, "raw_text": raw, "page": 1, "status": status}


def _citation(number, country, supported, flags=(), country_status=OK):
    return {
        "label": "D1",
        "number": _ev(number),
        "country": _ev(country, status=country_status),
        "country_supported": supported,
        "cited_paragraphs": _ev(["[0010]"]),
        "flags": list(flags),
    }


def _rej_fields(article, supported=True, citations=(), flags=()):
    return {
        "no": 1,
        "article": _ev(article),
        "supported": supported,
        "claims": _ev([1]),
        "citations": list(citations),
        "examiner_reasoning": _ev("요지"),
        "flags": list(flags),
    }


def _rej(article, supported=True, citations=(), flags=()):
    return build_rejection(document_id="d_1", **_rej_fields(article, supported, citations, flags))


def _oa(rejections, **override):
    none_value = {
        "value": None,
        "raw_text": None,
        "page": None,
        "status": Status(value=StatusValue.CONFIRMED, checked="원문에 칸 없음"),
    }
    fields = {
        "oa_id": "oa_1",
        "application_number": _ev("10-2099-0000001"),
        "dispatch_number": _ev("9-5-2099-000000001"),
        "notice_date": _ev(None, "2099.01.26"),
        "response_due": _ev(None, "2099.03.26"),
        "notice_kind": {**none_value, "value": "initial"},
        "examined_claims": _ev([1, 2, 3], "제1항 내지 제3항"),
        "examiner_hints": ExaminerHints(
            allowable_claims={**none_value, "value": []}, amendment_note=none_value
        ),
        "rejections": rejections,
    }
    fields.update(override)
    return build_oa_result(document_id="d_1", **fields)


def test_OAResult_안쪽_지원_안_하는_거절이유와_나라가_직접_검토_필요로_뜸():
    r0 = _rej("29-2")
    r1 = _rej(
        "42-3",
        supported=False,
        flags=[Flag.NEEDS_HUMAN_REVIEW],
        citations=[_citation("JP 2099-1", "JP", False, [Flag.NEEDS_HUMAN_REVIEW])],
    )
    items = collect_review_items([_oa([r0, r1])], _empty_materials())
    assert items == [
        ReviewItem(
            kind="needs_human_review",
            target="oa_result[0].rejections[1]",
            label="42-3",
            reason="지원 안 하는 거절이유 42-3",
        ),
        ReviewItem(
            kind="needs_human_review",
            target="oa_result[0].rejections[1].citations[0]",
            label="JP 2099-1",
            reason="지원 안 하는 나라 JP",
        ),
    ]


def test_제출기일과_거절이유_청구항이_확인되지_않으면_필드마다_한_줄():
    bad = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
    rej = build_rejection(
        document_id="d_1",
        no=1,
        article=_ev("29-2"),
        supported=True,
        claims=_ev(None, status=bad),
        citations=[],
        examiner_reasoning=_ev("요지"),
    )
    oa = _oa([rej], response_due=_ev(None, "2099.03.26", status=bad))
    assert collect_review_items([oa], _empty_materials()) == [
        ReviewItem(
            kind="unverified",
            target="oa_result[0].response_due",
            label="oa_1",
            reason="not_extracted",
        ),
        ReviewItem(
            kind="unverified",
            target="oa_result[0].rejections[0].claims",
            label="29-2",
            reason="not_extracted",
        ),
    ]


def test_청구항_못_뽑음과_인용_나라_못_정함은_필드마다_따로_한_줄씩():
    bad = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
    amb = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.AMBIGUOUS)
    c = _citation("US 2099/0000001", None, False, [Flag.NEEDS_HUMAN_REVIEW], amb)
    rej = build_rejection(
        document_id="d_1",
        no=1,
        article=_ev("29-2"),
        supported=True,
        claims=_ev(None, status=bad),
        citations=[c],
        examiner_reasoning=_ev("요지"),
    )
    target = "oa_result[0].rejections[0]"
    assert collect_review_items([_oa([rej])], _empty_materials()) == [
        ReviewItem(
            kind="unverified", target=f"{target}.claims", label="29-2", reason="not_extracted"
        ),
        ReviewItem(
            kind="unverified",
            target=f"{target}.citations[0].country",
            label="US 2099/0000001",
            reason="ambiguous",
        ),
        ReviewItem(
            kind="needs_human_review",
            target=f"{target}.citations[0]",
            label="US 2099/0000001",
            reason="나라를 못 정함 (원문)",
        ),
    ]


def test_지원_안_하는_거절이유_안의_확인되지_않은_필드도_한_줄씩():
    bad = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
    rej = build_rejection(
        document_id="d_1",
        no=1,
        article=_ev("42-3"),
        supported=False,
        claims=_ev(None, status=bad),
        citations=[],
        examiner_reasoning=_ev("요지"),
        flags=[Flag.NEEDS_HUMAN_REVIEW],
    )
    assert collect_review_items([_oa([rej])], _empty_materials()) == [
        ReviewItem(
            kind="unverified",
            target="oa_result[0].rejections[0].claims",
            label="42-3",
            reason="not_extracted",
        ),
        ReviewItem(
            kind="needs_human_review",
            target="oa_result[0].rejections[0]",
            label="42-3",
            reason="지원 안 하는 거절이유 42-3",
        ),
    ]


def test_충돌_필드는_conflict_한_줄():
    cands = [
        {"value": v, "raw_text": v, "page": 1, "source": s}
        for v, s in (("a", "rule"), ("b", "model"))
    ]
    conflict = {
        "value": None,
        "raw_text": None,
        "page": None,
        "status": Status(value=StatusValue.CONFLICT),
        "candidates": cands,
    }
    oa = _oa([_rej("29-2")], application_number=conflict)
    assert collect_review_items([oa], _empty_materials()) == [
        ReviewItem(
            kind="conflict",
            target="oa_result[0].application_number",
            label="oa_1",
            reason="값이 서로 충돌",
        )
    ]


def test_OAResult_결과가_여럿이어도_경로는_늘_oa_result_인덱스():
    bad = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
    oa = _oa([_rej("29-2")], response_due=_ev(None, "2099.03.26", status=bad))
    items = collect_review_items([_oa([_rej("29-2")]), oa], _empty_materials())
    assert [i.target for i in items] == ["oa_result[1].response_due"]


def test_OAResult_다시_확인_표시는_결과_자리에서_한_줄():
    oa = mark_recheck(_oa([_rej("29-2")]), "앞 입력이 바뀜")
    assert collect_review_items([oa], _empty_materials()) == [
        ReviewItem(
            kind="needs_recheck", target="oa_result[0]", label="oa_1", reason="앞 입력이 바뀜"
        )
    ]


def test_build_oa_result는_거절이유를_dict로_받아도_됨():
    oa = _oa([_rej_fields("29-2")])
    assert oa.rejections[0].article.value == "29-2"
    assert oa.rejections[0].evidence  # build_rejection으로 만들어짐


def test_OAResult가_멀쩡하면_검토할_사항_없음():
    assert collect_review_items([_oa([_rej("29-2")])], _empty_materials()) == []


def test_심사_대상_청구항이_확인되지_않으면_필드_한_줄로_검토_사항에_든다():
    bad = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
    oa = _oa([_rej("29-2")], examined_claims=_ev(None, "제1항 내지 제3항", status=bad))
    assert collect_review_items([oa], _empty_materials()) == [
        ReviewItem(
            kind="unverified",
            target="oa_result[0].examined_claims",
            label="oa_1",
            reason="not_extracted",
        )
    ]
