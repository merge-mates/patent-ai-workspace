import json
import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from patent_ai.core.schemas.case_materials import (
    CaseDocument,
    CaseMaterials,
    LookupResult,
    MissingMaterial,
)
from patent_ai.core.schemas.common import (
    Flag,
    ResultBase,
    Status,
    StatusValue,
    UnverifiedReason,
)
from patent_ai.core.schemas.oa_result import (
    ExaminerHints,
    OAResult,
    build_oa_result,
    build_rejection,
)
from patent_ai.core.schemas.propagation import (
    ReviewItem,
    collect_review_items,
    finalize_case_materials,
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
            target="oa_result[oa_1].rejections[1]",
            label="42-3",
            reason="지원 안 하는 거절이유 42-3",
        ),
        ReviewItem(
            kind="needs_human_review",
            target="oa_result[oa_1].rejections[1].citations[0]",
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
            target="oa_result[oa_1].response_due",
            label="oa_1",
            reason="not_extracted",
        ),
        ReviewItem(
            kind="unverified",
            target="oa_result[oa_1].rejections[0].claims",
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
    target = "oa_result[oa_1].rejections[0]"
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
            target="oa_result[oa_1].rejections[0].claims",
            label="42-3",
            reason="not_extracted",
        ),
        ReviewItem(
            kind="needs_human_review",
            target="oa_result[oa_1].rejections[0]",
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
            target="oa_result[oa_1].application_number",
            label="oa_1",
            reason="값이 서로 충돌",
        )
    ]


def test_OAResult_결과가_여럿이어도_경로는_목록_위치가_아니라_oa_id():
    bad = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
    second = _oa([_rej("29-2")], oa_id="oa_2", response_due=_ev(None, "2099.03.26", status=bad))
    items = collect_review_items([_oa([_rej("29-2")]), second], _empty_materials())
    assert [i.target for i in items] == ["oa_result[oa_2].response_due"]
    # 순서를 바꿔 넘겨도 같은 OA는 같은 경로
    items = collect_review_items([second, _oa([_rej("29-2")])], _empty_materials())
    assert [i.target for i in items] == ["oa_result[oa_2].response_due"]


def test_OAResult_다시_확인_표시는_결과_자리에서_한_줄():
    oa = mark_recheck(_oa([_rej("29-2")]), "앞 입력이 바뀜")
    assert collect_review_items([oa], _empty_materials()) == [
        ReviewItem(
            kind="needs_recheck", target="oa_result[oa_1]", label="oa_1", reason="앞 입력이 바뀜"
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
            target="oa_result[oa_1].examined_claims",
            label="oa_1",
            reason="not_extracted",
        )
    ]


# ---------- #18 task-6: 청구항 줄 ----------
def _row(**extra):
    data = {
        "claim": 1,
        "rejection": 1,
        "citations": ["D1"],
        "locations": {"D1": ["[0014]"]},
        "raw_text": "원문",
        "page": 3,
        "status": Status(value="confirmed", checked="3쪽 원문 대조"),
    }
    data.update(extra)
    return data


def _bad_row(**extra):
    data = {
        "claim": 2,
        "rejection": 1,
        "raw_text": None,
        "page": None,
        "status": Status(value="unverified", reason="not_extracted"),
    }
    data.update(extra)
    return data


def test_확인되지_않은_청구항_줄은_그_줄_경로에서_한_줄():
    oa = _oa([_rej("29-2")], claim_rows=[_row(), _bad_row()])
    items = collect_review_items([oa], CaseMaterials(case_id="c_1"))
    assert items == [
        ReviewItem(
            kind="unverified",
            target="oa_result[oa_1].claim_rows[1]",
            label="청구항 2·거절이유 1",
            reason="not_extracted",
        )
    ]


def test_청구항_번호를_못_읽은_줄은_이름만():
    oa = _oa([_rej("29-2")], claim_rows=[_bad_row(claim=None, rejection=None)])
    (item,) = collect_review_items([oa], CaseMaterials(case_id="c_1"))
    assert (item.target, item.label) == ("oa_result[oa_1].claim_rows[0]", "청구항 줄")


def test_확인됨_청구항_줄은_검토할_사항이_아니다():
    oa = _oa([_rej("29-2")], claim_rows=[_row()])
    assert collect_review_items([oa], CaseMaterials(case_id="c_1")) == []


# ---------- F5 마무리 함수 finalize_case_materials (design 2절) ----------

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
NOT_EXTRACTED = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
INPUT_UNV = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.INPUT_UNVERIFIED)


def _load(case: str) -> tuple[OAResult, CaseMaterials]:
    d = FIXTURES / case
    oa = OAResult.model_validate_json((d / "oa_result.json").read_text("utf-8"))
    m = CaseMaterials.model_validate_json((d / "case_materials.json").read_text("utf-8"))
    return oa, m


def _doc(document_id="doc_1", kind="oa", status=OK, text_status=None) -> CaseDocument:
    return CaseDocument(
        document_id=document_id,
        kind=kind,
        source="uploaded",
        status=status,
        text_status=text_status,
    )


def _missing(what="D2 본문") -> MissingMaterial:
    return MissingMaterial(what=what, lookup_result=LookupResult.BODY_MISSING, ask_upload=True)


def _pairs(m: CaseMaterials) -> list[tuple[str, str, str]]:
    return [(i.kind, i.target, i.reason) for i in m.review_items]


def test_마무리_스캔본은_원인_줄_하나와_묶은_줄_하나(caplog):
    oa, want = _load("f5/case_scanned")
    # 마무리 안 한 ⑥(목록 없음)에서 시작해도 fixture와 같은 ⑥이 나온다
    start = CaseMaterials(case_id="c_scanned", documents=want.documents)
    got = finalize_case_materials([oa], start)
    assert got == want
    assert got.review_items_count == len(got.review_items) == 2
    # 칸마다 줄이 아니라 결과마다 한 줄, 묶기 not_extracted 줄은 없음
    assert _pairs(got) == [
        ("unverified", "materials.documents[0]", "body_missing"),
        ("unverified", "oa_result[oa_1]", "앞 입력이 확인되지 않음: 칸 8개"),
    ]
    assert not caplog.records


def test_마무리_빠진_자료가_먼저고_그_밖_줄이_뒤에(caplog):
    oa, want = _load("case_missing_citation")
    start = want.model_copy(update={"review_items": None, "review_items_count": 0})
    got = finalize_case_materials([oa], start)
    assert [i.kind for i in got.review_items] == ["missing_material", "needs_human_review"]
    assert got.review_items[1].target == "oa_result[oa_1].rejections[2]"
    assert got == want


def test_마무리_결과_0개여도_빠진_자료_줄과_경고(caplog):
    m = CaseMaterials(case_id="c1", missing=[_missing()])
    with caplog.at_level(logging.WARNING):
        got = finalize_case_materials([], m)
    assert _pairs(got) == [("missing_material", "materials.missing[0]", "body_missing")]
    assert got.review_items_count == 1
    assert caplog.records


def test_마무리_다른_출원번호_문서는_충돌_줄_하나():
    conflict = Status(value=StatusValue.CONFLICT)
    m = CaseMaterials(case_id="c1", documents=[_doc(), _doc("doc_x", "claims", status=conflict)])
    got = finalize_case_materials([], m)
    (item,) = got.review_items
    assert item.kind == "conflict" and item.target == "materials.documents[1]"
    assert (item.label, item.reason) == ("claims doc_x", "값이 서로 충돌")
    assert got.review_items_count == 1


def test_마무리_다른_출원번호이면서_스캔본이면_원인이_달라_둘_다_남음():
    conflict = Status(value=StatusValue.CONFLICT)
    m = CaseMaterials(case_id="c1", documents=[_doc(status=conflict, text_status=UNV)])
    got = finalize_case_materials([], m)
    assert [(i.kind, i.reason) for i in got.review_items] == [
        ("conflict", "값이 서로 충돌"),
        ("unverified", "body_missing"),
    ]
    assert {i.target for i in got.review_items} == {"materials.documents[0]"}


def test_마무리_글자는_있는데_번호를_못_읽은_문서는_묶기_이유_한_줄():
    m = CaseMaterials(case_id="c1", documents=[_doc(status=NOT_EXTRACTED, text_status=OK)])
    got = finalize_case_materials([], m)
    assert _pairs(got) == [("unverified", "materials.documents[0]", "not_extracted")]


def test_마무리_글자_상태는_있고_확인됨이면_줄_없음():
    m = CaseMaterials(case_id="c1", documents=[_doc(text_status=OK)])
    assert finalize_case_materials([], m).review_items == []


def _empty_ev(status) -> dict:
    """글자도 쪽도 없는 칸 (앞 입력이 없어 읽지 못한 값)."""
    return {"value": None, "raw_text": None, "page": None, "status": status}


def test_마무리_결과마다_input_unverified_필드는_한_줄로_묶고_원인_줄은_그대로():
    # 같은 사건의 OA 둘: oa_1은 필드 둘이 앞 입력 때문, 하나는 원인(not_extracted)
    first = _oa(
        [_rej("29-2")],
        application_number=_empty_ev(INPUT_UNV),
        dispatch_number=_empty_ev(INPUT_UNV),
        response_due=_ev(None, "2099.03.26", status=NOT_EXTRACTED),
    )
    second = _oa([_rej("29-2")], oa_id="oa_2", notice_date=_empty_ev(INPUT_UNV))
    got = finalize_case_materials([first, second], _empty_materials())
    assert [(i.target, i.label, i.reason) for i in got.review_items] == [
        # 묶은 줄은 그 결과의 첫 줄 자리 (application_number가 response_due보다 앞 칸)
        ("oa_result[oa_1]", "oa_1", "앞 입력이 확인되지 않음: 칸 2개"),
        ("oa_result[oa_1].response_due", "oa_1", "not_extracted"),
        ("oa_result[oa_2]", "oa_2", "앞 입력이 확인되지 않음: 칸 1개"),
    ]
    assert got.review_items_count == 3


def test_마무리_종류가_섞이면_정한_순서로():
    # 결과 쪽 줄(직접 검토·확인되지 않음·다시 확인)과 문서 줄(충돌), 빠진 자료를 섞어 넣는다
    bad = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
    rej = _rej("42-3", supported=False, flags=[Flag.NEEDS_HUMAN_REVIEW])
    oa = mark_recheck(
        _oa([rej], response_due=_ev(None, "2099.03.26", status=bad)), "앞 입력이 바뀜"
    )
    judge = ResultBase(status=OK, flags=[Flag.NEEDS_HUMAN_JUDGMENT])
    m = CaseMaterials(
        case_id="c1",
        documents=[_doc("doc_x", status=Status(value=StatusValue.CONFLICT))],
        missing=[_missing()],
    )
    got = finalize_case_materials([oa, judge], m)
    assert [i.kind for i in got.review_items] == [
        "missing_material",
        "conflict",
        "unverified",
        "needs_human_judgment",
        "needs_human_review",
        "needs_recheck",
    ]


def test_마무리_같은_열쇠가_두_번_나오면_하나():
    bad = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
    a = _oa([_rej("29-2")], response_due=_ev(None, "2099.03.26", status=bad))
    b = _oa([_rej("29-2")], response_due=_ev(None, "2099.03.26", status=bad))  # 같은 oa_id
    got = finalize_case_materials([a, b], _empty_materials())
    assert _pairs(got) == [("unverified", "oa_result[oa_1].response_due", "not_extracted")]


def test_마무리는_입력을_바꾸지_않고_새_6번을_돌려준다():
    m = CaseMaterials(case_id="c1", missing=[_missing()])
    got = finalize_case_materials([], m)
    assert m.review_items is None and m.review_items_count == 0
    assert got is not m and got.review_items_count == 1
    # 다시 마무리해도 줄이 불어나지 않는다 (입력의 옛 목록은 버리고 새로 모음)
    again = finalize_case_materials([], got)
    assert again == got
    # 줄 수를 잘못 맞춘 채 넘기는 일은 없다 (검사를 거친 값)
    CaseMaterials.model_validate(json.loads(got.model_dump_json()))


def test_마무리_모으다_예외가_나면_삼키지_않고_올린다():
    with pytest.raises(AttributeError):
        finalize_case_materials([object()], _empty_materials())  # type: ignore[list-item]
