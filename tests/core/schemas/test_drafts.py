"""Drafts(⑤) 테스트. 기대값은 이슈 #164 설계와 docs/data-model.md 4절."""

import pytest
from pydantic import ValidationError

from patent_ai.core.schemas.common import Evidence, Status
from patent_ai.core.schemas.drafts import (
    AmendedClaim,
    BasedOn,
    Drafts,
    OpinionKey,
    OpinionSection,
)

OK = Status(value="confirmed", checked="원문 대조")


def sec(key="case_info", **kw):
    data = {"key": key, "title": "제목", "ai_text": "AI 원문"}
    data.update(kw)
    return OpinionSection(**data)


def claim(**kw):
    data = {
        "claim": 1,
        "unit_id": "oa_1:29-2:c1",
        "before": "OA 당시 청구항",
        "ai_text": "보정 초안",
        "spec_basis": [Evidence(document_id="d_spec", location="[0016]")],
        "held_reason": None,
    }
    data.update(kw)
    return AmendedClaim(**data)


def held(**kw):
    data = {"ai_text": None, "held_reason": "방향을 골라 주세요", "spec_basis": []}
    data.update(kw)
    return claim(**data)


def drafts(**kw):
    data = {
        "status": OK,
        "draft_id": "dr_1",
        "based_on": [BasedOn(unit_id="oa_1:29-2:c1", candidate_id="c1")],
        "opinion": [sec(k) for k in OpinionKey],
        "claims": [claim()],
    }
    data.update(kw)
    return Drafts(**data)


# ---------- AI 원문 보존 ----------


@pytest.mark.parametrize("text", ["", "  \n"])
def test_ai_text_공백_거부(text):
    with pytest.raises(ValidationError, match="ai_text"):
        sec(ai_text=text)


def test_ai_text는_None도_거부():
    with pytest.raises(ValidationError):
        sec(ai_text=None)


def test_human_text만_있고_origin이_ai_generated면_거부():
    with pytest.raises(ValidationError, match="human_edited"):
        sec(human_text="고침")


def test_human_edited인데_human_text_없으면_거부():
    with pytest.raises(ValidationError, match="human_edited"):
        sec(origin="human_edited")


def test_human_edited면_ai_text가_그대로_남는다():
    s = sec(human_text="고침", origin="human_edited")
    assert s.ai_text == "AI 원문"
    assert s.human_text == "고침"


def test_human_text가_공백이면_거부():
    with pytest.raises(ValidationError, match="human_text"):
        sec(human_text=" ", origin="human_edited")


def test_origin은_두_값만():
    with pytest.raises(ValidationError, match="origin"):
        sec(origin="ai_default")


def test_보정_청구항_사람_수정():
    c = claim(human_text="고친 초안", origin="human_edited")
    assert c.ai_text == "보정 초안"


def test_보정_청구항_ai_text_공백_거부():
    with pytest.raises(ValidationError, match="ai_text"):
        claim(ai_text=" ")


def test_보정_청구항_human_text만_있고_origin_ai_generated면_거부():
    with pytest.raises(ValidationError, match="human_edited"):
        claim(human_text="고침")


# ---------- 보류 청구항 ----------


def test_보류_청구항_통과():
    c = held()
    assert c.ai_text is None and c.held_reason


def test_ai_text_없는데_보류_이유_없으면_거부():
    with pytest.raises(ValidationError, match="held_reason"):
        held(held_reason=None)


def test_ai_text_있는데_보류_이유_있으면_거부():
    with pytest.raises(ValidationError, match="held_reason"):
        claim(held_reason="이유")


def test_보류_청구항에_human_text_거부():
    with pytest.raises(ValidationError, match="human_text"):
        held(human_text="고침", origin="human_edited")


# ---------- Drafts ----------


def test_opinion_순서가_다르면_거부():
    with pytest.raises(ValidationError, match="순서"):
        drafts(opinion=[sec("points"), sec("case_info")])


def test_opinion_key_중복_거부():
    with pytest.raises(ValidationError, match="중복"):
        drafts(opinion=[sec("case_info"), sec("case_info")])


def test_based_on_unit_중복_거부():
    with pytest.raises(ValidationError, match="중복"):
        drafts(
            based_on=[
                BasedOn(unit_id="oa_1:29-2:c1", candidate_id="a"),
                BasedOn(unit_id="oa_1:29-2:c1", candidate_id="b"),
            ]
        )


def test_opinion_key_순서_코드():
    assert [k.value for k in OpinionKey] == [
        "case_info", "points", "response", "amendment", "closing",
    ]  # fmt: skip


def test_extra_칸_거부():
    with pytest.raises(ValidationError):
        drafts(check={})
    with pytest.raises(ValidationError):
        sec(extra=1)


def test_왕복():
    d = drafts(
        opinion=[
            sec(k, human_text="고침", origin="human_edited") if k == "points" else sec(k)
            for k in OpinionKey
        ],
        claims=[
            claim(human_text="고친 초안", origin="human_edited"),
            held(unit_id="oa_1:29-2:c5", claim=5),
        ],
    )
    again = Drafts.model_validate(d.model_dump(mode="json"))
    assert again == d


def test_opinion이_비면_거부():
    with pytest.raises(ValidationError, match="opinion"):
        drafts(opinion=[])


def test_claims_based_on은_비어도_통과():
    d = drafts(claims=[], based_on=[])
    assert d.claims == [] and d.based_on == []


def test_보류_청구항은_spec_basis가_비어야_함():
    with pytest.raises(ValidationError, match="spec_basis"):
        held(spec_basis=[Evidence(document_id="d_spec", location="[0016]")])


def test_초안_unit_id_꼴이_틀리면_거부():
    with pytest.raises(ValidationError, match="unit_id 꼴"):
        BasedOn(unit_id="nonsense", candidate_id="c1")
    with pytest.raises(ValidationError, match="unit_id 꼴"):
        claim(unit_id="nonsense")
