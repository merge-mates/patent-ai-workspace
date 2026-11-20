"""LegalEvidenceBundle(④) 테스트. 기대값은 이슈 #164 설계와 docs/data-model.md 3절."""

from datetime import date

import pytest
from pydantic import ValidationError

from patent_ai.core.schemas.common import Evidence, Status, StatusValue
from patent_ai.core.schemas.legal_evidence import (
    ALL_CLAIMS_CHECKED,
    ALL_SOURCES_CHECKED,
    LegalClaim,
    LegalEvidenceBundle,
    LegalSource,
    summarize_bundle_status,
    summarize_claim_status,
)

OK = Status(value="confirmed", checked="원문 대조")
UNKNOWN_EDITION = Status(value="unverified", reason="edition_unknown")
NOT_EXTRACTED = Status(value="unverified", reason="not_extracted")


def source(kind="statute", edition="2024-01-01 시행", status=OK, **kw):
    data = {
        "source_kind": kind,
        "identifier": "특허법 제29조 제2항",
        "text_kind": "full",
        "evidence": Evidence(
            document_id="law_patent",
            location="제29조 제2항",
            raw_text="발췌 문장",
            edition=edition,
            checked_on=date(2026, 11, 20),
        ),
        "status": status,
    }
    data.update(kw)
    return LegalSource(**data)


def claim(no=1, sources=None, status=None, **kw):
    sources = [source()] if sources is None else sources
    data = {
        "no": no,
        "text": "진보성은 선행기술로 쉽게 발명할 수 있으면 부정된다",
        "sources": sources,
        "status": status or summarize_claim_status(sources),
    }
    data.update(kw)
    return LegalClaim(**data)


def bundle(claims=None, status=None, **kw):
    claims = [claim()] if claims is None else claims
    data = {
        "bundle_id": "lb_1",
        "unit_id": "oa_1:29-2:c1",
        "question": "진보성 판단 기준은?",
        "as_of": None,
        "checked_on": date(2026, 11, 20),
        "claims": claims,
        "status": status or summarize_bundle_status(claims),
    }
    data.update(kw)
    return LegalEvidenceBundle(**data)


# ---------- 근거 하나: 판본 ----------


@pytest.mark.parametrize("kind", ["statute", "exam_guideline"])
@pytest.mark.parametrize("edition", [None, "", "   "])
def test_판본_없는_법령_심사기준은_confirmed_불가(kind, edition):
    with pytest.raises(ValidationError):
        source(kind=kind, edition=edition)


def test_판본_없어도_unverified_edition_unknown은_통과():
    s = source(edition=None, status=UNKNOWN_EDITION)
    assert s.status.reason == "edition_unknown"


def test_판례는_판본_없이_confirmed_통과():
    s = source(kind="precedent", edition=None, identifier="대법원 2020후1234", speaker="court")
    assert s.status.value == StatusValue.CONFIRMED


def test_법령_심사기준은_speaker_거부():
    with pytest.raises(ValidationError):
        source(kind="statute", speaker="court")
    with pytest.raises(ValidationError):
        source(kind="exam_guideline", speaker="party")


def test_심결례는_speaker_가능():
    assert source(kind="trial_decision", edition=None, speaker="party").speaker == "party"


def test_identifier는_비지_않음():
    with pytest.raises(ValidationError):
        source(identifier="  ")


# ---------- 주장·묶음 status ----------


def test_주장_status가_가장_나쁜_값과_다르면_거부():
    bad_src = source(edition=None, status=UNKNOWN_EDITION)
    with pytest.raises(ValidationError):
        claim(sources=[source(), bad_src], status=OK)


def test_주장_status가_가장_나쁜_값과_같으면_통과():
    bad_src = source(edition=None, status=UNKNOWN_EDITION)
    c = claim(sources=[source(), bad_src])
    assert c.status.value == StatusValue.UNVERIFIED
    assert c.status.reason == "edition_unknown"


def test_주장_모두_confirmed면_checked_상수():
    assert claim().status.checked == ALL_SOURCES_CHECKED


def test_묶음_status가_가장_나쁜_값과_다르면_거부():
    bad = claim(2, sources=[source(edition=None, status=UNKNOWN_EDITION)])
    with pytest.raises(ValidationError):
        bundle(claims=[claim(1), bad], status=OK)


def test_묶음_status가_가장_나쁜_값과_같으면_통과():
    bad = claim(2, sources=[source(edition=None, status=UNKNOWN_EDITION)])
    b = bundle(claims=[claim(1), bad])
    assert b.status.value == StatusValue.UNVERIFIED


def test_묶음_모두_confirmed면_checked_상수():
    assert bundle().status.checked == ALL_CLAIMS_CHECKED


def test_주장_0개_묶음은_not_extracted일_때만_통과():
    b = bundle(claims=[], status=NOT_EXTRACTED)
    assert b.status.reason == "not_extracted"
    with pytest.raises(ValidationError):
        bundle(claims=[], status=OK)


def test_근거_0개_주장은_not_extracted일_때만_통과():
    # 근거를 못 찾은 주장은 F2에서 평소에 나온다. 근거 없이 확인됨일 수는 없다
    c = claim(sources=[], status=NOT_EXTRACTED)
    assert c.status.reason == "not_extracted"
    with pytest.raises(ValidationError):
        claim(sources=[], status=OK)


def test_no_중복_거부():
    with pytest.raises(ValidationError):
        bundle(claims=[claim(1), claim(1)])


def test_no는_1부터():
    with pytest.raises(ValidationError):
        claim(no=0)


def test_주장_문장은_비지_않음():
    with pytest.raises(ValidationError):
        claim(text=" ")


# ---------- 적용된다 칸 없음 ----------


def test_적용된다_칸_없음():
    for model in (LegalSource, LegalClaim, LegalEvidenceBundle):
        for name in model.model_fields:
            assert "appl" not in name.lower()
    with pytest.raises(ValidationError):
        bundle(applies=True)


# ---------- 왕복 ----------


def test_왕복():
    b = bundle(
        claims=[
            claim(
                1,
                sources=[
                    source(),
                    source("precedent", None, identifier="대법원 2020후1234", speaker="court"),
                ],
            ),
            claim(
                2, sources=[source("exam_guideline", "2024-03 개정", identifier="심사지침 5부 3장")]
            ),
        ],
        as_of=date(2026, 1, 1),
        further_review=["최신 개정 여부"],
    )
    again = LegalEvidenceBundle.model_validate(b.model_dump(mode="json"))
    assert again == b


def test_묶음_unit_id_꼴이_틀리면_거부_null은_통과():
    data = bundle().model_dump(mode="json")
    with pytest.raises(ValidationError, match="unit_id 꼴"):
        LegalEvidenceBundle.model_validate({**data, "unit_id": "nonsense"})
    # 법률 질문 흐름은 판단 단위가 없다
    assert LegalEvidenceBundle.model_validate({**data, "unit_id": None}).unit_id is None
