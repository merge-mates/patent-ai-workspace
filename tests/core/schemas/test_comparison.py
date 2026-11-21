"""ComparisonTable(③)·ClarityReview 테스트. 기대값은 이슈 #164 설계와 docs/data-model.md 3절."""

import logging

import pytest
from pydantic import ValidationError

from patent_ai.core.schemas.common import Evidence, Flag, Status, StatusValue
from patent_ai.core.schemas.comparison import (
    ALL_ROWS_CHECKED,
    ClarityReview,
    ComparedCitation,
    ComparisonRow,
    ComparisonTable,
    summarize_table_status,
)

OK = Status(value="confirmed", checked="D1 원문 대조")
BAD = Status(value="unverified", reason="ambiguous")


def row(citation="D1", status=OK, **kw):
    data = {
        "status": status,
        "evidence": [Evidence(document_id="d_D1", location="[0016]")],
        "claim": 1,
        "element": "센서",
        "element_location": "청구항 1 둘째 줄",
        "citation": citation,
        "judgment": "disclosed",
        "paragraph_source": "examiner",
    }
    data.update(kw)
    return ComparisonRow(**data)


def cite(label="D1", compared=True, **kw):
    data = {"label": label, "number": "KR20990000001A", "compared": compared}
    if not compared:
        data.update(
            skipped_reason="지원 안 하는 나라 (JP)",
            skipped_status=Status(value="unverified", reason="lookup_failed"),
        )
    data.update(kw)
    return ComparedCitation(**data)


INVENTIVE = {
    "kind": "inventive_step",
    "differences": ["온도 센서"],
    "combination": "D1에 D2를 결합",
    "effect_candidates": ["정확도 향상"],
}
NOVELTY = {"kind": "novelty", "citation": "D1", "verdict": "no_difference", "reason": "같음"}


def table(kind="inventive_step", rows=None, citations=None, summary=None, status=None, **kw):
    rows = [row()] if rows is None else rows
    data = {
        "status": status or summarize_table_status(rows),
        "unit_id": "oa_1:29-2:c1",
        "rejection_kind": kind,
        "citations": citations if citations is not None else [cite()],
        "rows": rows,
        "summary": summary or (NOVELTY if kind == "novelty" else INVENTIVE),
    }
    data.update(kw)
    return ComparisonTable(**data)


# ---------- 갈림: 진보성·신규성은 대비표, 명확성은 ClarityReview ----------


def test_진보성_대비표():
    t = table("inventive_step", citations=[cite("D1"), cite("D2")], rows=[row("D1"), row("D2")])
    assert t.summary.kind == "inventive_step"
    assert t.status.value == StatusValue.CONFIRMED
    assert t.status.checked == ALL_ROWS_CHECKED


def test_신규성_대비표():
    t = table("novelty")
    assert t.summary.kind == "novelty"
    assert t.summary.citation == "D1"


@pytest.mark.parametrize("kind", ["clarity", "other"])
def test_대비표는_명확성_other를_거부(kind):
    # 요약 종류는 진보성으로 맞춰 두어, 종류 검사가 막는 것임을 메시지로 확인
    with pytest.raises(ValidationError, match="novelty·inventive_step만"):
        table(kind, summary=INVENTIVE)


def test_명확성은_ClarityReview로():
    review = ClarityReview(
        status=OK,
        unit_id="oa_1:42-4-2:c3",
        claim=3,
        term="약 50도",
        claim_location="청구항 3 셋째 줄",
        spec_definition=Evidence(document_id="d_spec", location="[0016]"),
        note="명세서에 정의가 있음",
    )
    assert review.spec_definition.location == "[0016]"
    assert ClarityReview.model_fields.keys() >= {"claim", "term", "claim_location", "note"}


def test_요약_종류가_거절이유와_다르면_거부():
    with pytest.raises(ValidationError):
        table("novelty", summary=INVENTIVE)
    with pytest.raises(ValidationError):
        table("inventive_step", summary=NOVELTY)


def test_요약은_kind로_갈린다():
    with pytest.raises(ValidationError):
        table("inventive_step", summary={"kind": "other", "reason": "x"})


# ---------- 신규성은 인용 하나 ----------


def test_신규성에_대비한_인용이_둘이면_거부():
    with pytest.raises(ValidationError):
        table("novelty", citations=[cite("D1"), cite("D2")], rows=[row("D1")])


def test_신규성에_대비한_인용이_없으면_거부():
    with pytest.raises(ValidationError):
        table(
            "novelty", citations=[cite("D1", compared=False)], rows=[], flags=["needs_human_review"]
        )


def test_신규성_요약_인용이_다르면_거부():
    with pytest.raises(ValidationError):
        table("novelty", summary={**NOVELTY, "citation": "D2"})


def test_신규성은_대비_안_한_인용이_더_있어도_하나만_대비하면_통과():
    t = table(
        "novelty",
        citations=[cite("D1"), cite("D2", compared=False)],
        flags=["needs_human_review"],
    )
    assert [c.label for c in t.citations if c.compared] == ["D1"]


# ---------- 인용·줄 ----------


def test_인용_라벨_중복_거부():
    with pytest.raises(ValidationError):
        table(citations=[cite("D1"), cite("D1")])


def test_줄의_인용은_대비한_인용이어야_함():
    with pytest.raises(ValidationError):
        table(rows=[row("D9")])
    with pytest.raises(ValidationError):  # 지원 안 하는 인용으로는 줄을 못 만든다
        table(
            citations=[cite("D1"), cite("D2", compared=False)],
            rows=[row("D2")],
            flags=["needs_human_review"],
        )


def test_지원_안_하는_나라는_flags로만_status는_그대로():
    t = table(
        citations=[cite("D1"), cite("D2", compared=False)],
        flags=["needs_human_review"],
    )
    assert Flag.NEEDS_HUMAN_REVIEW in t.flags
    assert t.status.value == StatusValue.CONFIRMED


def test_대비_안_한_인용이_있는데_flags_없으면_거부():
    with pytest.raises(ValidationError):
        table(citations=[cite("D1"), cite("D2", compared=False)])


def test_대비한_인용은_skipped_칸이_null_안_한_인용은_둘_다_채움():
    with pytest.raises(ValidationError):
        cite("D1", skipped_reason="이유")
    with pytest.raises(ValidationError):
        ComparedCitation(label="D2", number="JP1A", compared=False, skipped_reason="이유")
    with pytest.raises(ValidationError):
        ComparedCitation(label="D2", number="JP1A", compared=False, skipped_status=BAD)


# ---------- status = 가장 나쁜 값 ----------


def test_결과_status는_rows_가장_나쁜_값과_같아야_함():
    rows = [row("D1"), row("D1", status=BAD)]
    assert summarize_table_status(rows).value == StatusValue.UNVERIFIED
    assert table(rows=rows).status.value == StatusValue.UNVERIFIED
    with pytest.raises(ValidationError):
        table(rows=rows, status=OK)


def test_rows가_비면_unverified와_경고(caplog):
    with caplog.at_level(logging.WARNING):
        s = summarize_table_status([])
    assert s.value == StatusValue.UNVERIFIED
    assert s.reason == "not_extracted"
    assert caplog.records


# ---------- why_retrieved ----------


def test_why_retrieved는_ai_found일_때만_꼭():
    r = row(paragraph_source="ai_found", why_retrieved="요소 문구와 같은 표현")
    assert r.why_retrieved
    with pytest.raises(ValidationError):
        row(paragraph_source="ai_found")
    with pytest.raises(ValidationError):
        row(paragraph_source="ai_found", why_retrieved="  ")
    with pytest.raises(ValidationError):
        row(paragraph_source="examiner", why_retrieved="이유")


# ---------- 모르는 칸 ----------


def test_모르는_칸은_거부():
    with pytest.raises(ValidationError):
        row(search_index="x")
    with pytest.raises(ValidationError):
        table(extra="x")
    with pytest.raises(ValidationError):
        cite("D1", extra="x")
    with pytest.raises(ValidationError):
        ClarityReview(
            status=OK,
            unit_id="oa_1:42-4-2:c1",
            claim=1,
            term="t",
            claim_location="l",
            note="n",
            extra="x",
        )


def test_명확성_claim은_unit_id의_c번호와_같아야_함():
    with pytest.raises(ValidationError, match="c번호"):
        ClarityReview(
            status=BAD,
            unit_id="oa_1:42-4-2:c3",
            claim=1,
            term="t",
            claim_location="l",
            note="n",
        )


@pytest.mark.parametrize("note", ["", "  "])
def test_명확성_note는_비지_않는다(note):
    with pytest.raises(ValidationError, match="note"):
        ClarityReview(
            status=OK,
            unit_id="oa_1:42-4-2:c1",
            claim=1,
            term="t",
            claim_location="l",
            note=note,
        )


def test_명확성_term은_비지_않는다():
    with pytest.raises(ValidationError):
        ClarityReview(
            status=OK, unit_id="oa_1:42-4-2:c1", claim=1, term=" ", claim_location="l", note="n"
        )


# ---------- 왕복 (서버가 결과를 jsonb 한 칸에 저장) ----------


@pytest.mark.parametrize("kind", ["inventive_step", "novelty"])
def test_ComparisonTable_왕복(kind):
    t = table(
        kind,
        citations=[cite("D1"), cite("D2", compared=False)],
        rows=[row("D1", paragraph_source="ai_found", why_retrieved="같은 표현")],
        flags=["needs_human_review"],
    )
    dumped = t.model_dump(mode="json")
    assert ComparisonTable.model_validate(dumped) == t
    assert dumped["summary"]["kind"] == kind


def test_ClarityReview_왕복():
    review = ClarityReview(
        status=OK,
        unit_id="oa_1:42-4-2:c3",
        claim=3,
        term="약 50도",
        claim_location="청구항 3",
        spec_definition=Evidence(document_id="d_spec", location="[0016]"),
        note="정의 있음",
    )
    assert ClarityReview.model_validate(review.model_dump(mode="json")) == review
    # 정의가 없으면 confirmed일 수 없으니 status도 같이 바꿔 다시 만든다
    none_def = ClarityReview.model_validate(
        {**review.model_dump(), "spec_definition": None, "status": BAD}
    )
    assert ClarityReview.model_validate(none_def.model_dump(mode="json")) == none_def


def test_대비표_unit_id_꼴이_틀리면_거부():
    # 결과끼리 unit_id로 잇기 때문에 꼴이 틀린 ID는 저장 전에 막는다 (#164 이슈 리뷰)
    data = table().model_dump(mode="json")
    with pytest.raises(ValidationError, match="unit_id 꼴"):
        ComparisonTable.model_validate({**data, "unit_id": "nonsense"})


def test_대비표_줄은_청구항_번호가_필수이고_1부터():
    data = row().model_dump()
    del data["claim"]
    with pytest.raises(ValidationError):
        ComparisonRow.model_validate(data)
    with pytest.raises(ValidationError):
        row(claim=0)
    assert row(claim=3).claim == 3


# ---------- 리뷰 반영 (PR #176) ----------


def test_개시됨_confirmed_줄은_근거_필수():
    with pytest.raises(ValidationError, match="evidence"):
        row(judgment="disclosed", status=OK, evidence=[])


@pytest.mark.parametrize("judgment", ["difference_candidate", "unclear"])
def test_차이후보_불명은_근거_없이_confirmed_통과(judgment):
    # 차이 후보는 인용문헌에 그 구성이 없다는 뜻이라 근거 위치가 없을 수 있다
    assert row(judgment=judgment, status=OK, evidence=[]).evidence == []


def test_개시됨이어도_confirmed가_아니면_근거_없이_통과():
    assert row(judgment="disclosed", status=BAD, evidence=[]).evidence == []


def test_ClarityReview_물려받은_evidence는_비어_있어야_함():
    with pytest.raises(ValidationError, match="evidence"):
        ClarityReview(
            status=BAD,
            unit_id="oa_1:42-4-2:c1",
            claim=1,
            term="t",
            claim_location="l",
            note="n",
            evidence=[Evidence(document_id="d")],
        )


def test_ClarityReview_confirmed는_spec_definition_필수():
    with pytest.raises(ValidationError, match="spec_definition"):
        ClarityReview(
            status=OK,
            unit_id="oa_1:42-4-2:c1",
            claim=1,
            term="t",
            claim_location="l",
            note="n",
            spec_definition=None,
        )


def test_ClarityReview_confirmed가_아니면_정의_없이_통과():
    r = ClarityReview(
        status=BAD, unit_id="oa_1:42-4-2:c1", claim=1, term="t", claim_location="l", note="n"
    )
    assert r.spec_definition is None
