"""LegalEvidenceBundle(④) 테스트. 기대값은 이슈 #164 설계와 docs/data-model.md 3절."""

from datetime import date

import pytest
from pydantic import ValidationError

from patent_ai.core.schemas.common import Evidence, Status, StatusValue
from patent_ai.core.schemas.legal_evidence import (
    ALL_CLAIMS_CHECKED,
    ALL_SOURCES_CHECKED,
    FurtherReview,
    LegalClaim,
    LegalEvidenceBundle,
    LegalQuestion,
    LegalSource,
    LegalSourceKind,
    Review,
    SearchLogEntry,
    summarize_bundle_status,
    summarize_claim_status,
)

OK = Status(value="confirmed", checked="원문 대조")
UNKNOWN_EDITION = Status(value="unverified", reason="edition_unknown")
NOT_EXTRACTED = Status(value="unverified", reason="not_extracted")


def source(kind="statute", edition="2024-01-01 시행", status=OK, **kw):
    case = kind in ("precedent", "trial")
    data = {
        "source_kind": kind,
        "identifier": "특허법 제29조 제2항",
        "text_kind": "full" if case else None,
        "speaker": "court" if case else None,
        "evidence": Evidence(
            document_id="law_patent",
            location="제29조 제2항",
            raw_text="발췌 문장",
            edition=edition,
            checked_on=date(2026, 11, 20),
            chunk_id="law_patent#12",
            index_version="law-idx-v2",
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
    if sources:  # 근거가 있으면 검토 결과도 기본으로 붙인다 (없으면 needs_human_review 필요)
        data["review"] = Review(verdict="supported", reason="근거가 뒷받침")
    data.update(kw)
    return LegalClaim(**data)


def question(**kw):
    data = {
        "text": "진보성 판단 기준은?",
        "source": "oa_rejection",
        "as_of": None,
        "as_of_source": "none",
        "source_kinds": ["statute", "precedent"],
        "article_refs": ["특허법 제29조 제2항"],
    }
    data.update(kw)
    return LegalQuestion(**data)


def bundle(claims=None, status=None, **kw):
    claims = [claim()] if claims is None else claims
    data = {
        "bundle_id": "lb_1",
        "unit_id": "oa_1:29-2:c1",
        "oa_id": "oa_1",
        "rejection": 1,
        "question": question(),
        "checked_on": date(2026, 11, 20),
        "claims": claims,
        "status": status or summarize_bundle_status(claims),
    }
    data.update(kw)
    return LegalEvidenceBundle(**data)


# ---------- 근거 하나: 판본 ----------


@pytest.mark.parametrize("kind", ["statute", "guideline"])
@pytest.mark.parametrize("edition", [None, "", "   "])
def test_판본_없는_법령_심사기준은_confirmed_불가(kind, edition):
    with pytest.raises(ValidationError):
        source(kind=kind, edition=edition)


def test_판본_없어도_unverified_edition_unknown은_통과():
    s = source(edition=None, status=UNKNOWN_EDITION)
    assert s.status.reason == "edition_unknown"


def test_판례는_판본_없이_confirmed_통과():
    s = source(kind="precedent", edition=None, identifier="대법원 2020후1234")
    assert s.status.value == StatusValue.CONFIRMED


# ---------- 근거 하나: 원문 위치 (#28 합격 기준 1, requirements 4) ----------


@pytest.mark.parametrize("kind", ["statute", "guideline", "precedent", "trial"])
@pytest.mark.parametrize("location", [None, "", "   "])
def test_원문_위치_없는_근거는_confirmed_불가(kind, location):
    ev = source(kind=kind).evidence.model_copy(update={"location": location})
    with pytest.raises(ValidationError):
        source(kind=kind, evidence=ev)


def test_원문_위치_없어도_unverified는_통과():
    ev = source().evidence.model_copy(update={"location": None})
    s = source(evidence=ev, status=UNKNOWN_EDITION)
    assert s.evidence.location is None


def test_법령_심사기준은_speaker_거부():
    with pytest.raises(ValidationError):
        source(kind="statute", speaker="court")
    with pytest.raises(ValidationError):
        source(kind="guideline", speaker="party")


@pytest.mark.parametrize("kind", ["statute", "guideline"])
@pytest.mark.parametrize(
    "extra",
    [
        {"text_kind": "full"},
        {"decided_on": date(2020, 1, 1)},
        {"court": "대법원"},
    ],
)
def test_법령_심사기준은_text_kind_decided_on_court도_null(kind, extra):
    with pytest.raises(ValidationError):
        source(kind=kind, **extra)


def test_심결은_speaker_가능():
    assert source(kind="trial", edition=None, speaker="party").speaker == "party"


@pytest.mark.parametrize("kind", ["precedent", "trial"])
@pytest.mark.parametrize("missing", ["text_kind", "speaker"])
def test_판례_심결은_text_kind와_speaker_필수(kind, missing):
    with pytest.raises(ValidationError):
        source(kind=kind, edition=None, **{missing: None})


def test_판례는_선고일_법원_가능_모르면_null():
    s = source(kind="precedent", edition=None, decided_on=date(2020, 5, 1), court="대법원")
    assert s.decided_on == date(2020, 5, 1) and s.court == "대법원"
    assert source(kind="precedent", edition=None).decided_on is None


def test_자료_종류_값은_색인_source_kind와_같다():
    assert {k.value for k in LegalSourceKind} == {"statute", "guideline", "precedent", "trial"}


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


NOT_FOUND = Status(value="not_found_in_scope", searched_scope="law-idx-v2 특허법, 2024-01-01")
CONFLICT = Status(value="conflict")


@pytest.mark.parametrize("empty_status", [NOT_EXTRACTED, NOT_FOUND])
def test_주장_0개_묶음은_unverified나_조회범위내없음으로_저장(empty_status):
    # F2 design 2절: 결과가 모두 비어도 ④를 저장, status는 not_found_in_scope + 찾아본 범위
    assert bundle(claims=[], status=empty_status).status.value == empty_status.value


@pytest.mark.parametrize("bad", [OK, CONFLICT])
def test_주장_0개_묶음은_확인됨_충돌_불가(bad):
    with pytest.raises(ValidationError, match="비어"):
        bundle(claims=[], status=bad)


@pytest.mark.parametrize("empty_status", [NOT_EXTRACTED, NOT_FOUND])
def test_근거_0개_주장은_unverified나_조회범위내없음으로_저장(empty_status):
    # 근거를 못 찾은 주장은 F2에서 평소에 나온다 (출처 확인에서 근거가 다 빠진 경우 포함)
    assert claim(sources=[], status=empty_status).status.value == empty_status.value


@pytest.mark.parametrize("bad", [OK, CONFLICT])
def test_근거_0개_주장은_확인됨_충돌_불가(bad):
    with pytest.raises(ValidationError, match="비어"):
        claim(sources=[], status=bad)


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
                    source(
                        "precedent",
                        None,
                        identifier="대법원 2020후1234",
                        decided_on=date(2020, 5, 1),
                        court="대법원",
                    ),
                ],
            ),
            claim(
                2,
                sources=[source("guideline", "2024-03 개정", identifier="심사지침 5부 3장")],
                review=Review(verdict="partial", reason="일부만 뒷받침"),
                flags=["needs_human_review"],
            ),
        ],
        question=question(
            as_of=date(2026, 1, 1), as_of_source="user_text", article_refs=["특허법 제29조"]
        ),
        clarifications=["2024년 개정 전후 모두 확인"],
        further_review=[
            FurtherReview(chunk_id="prec_1#4", why="opposite_holding", note="반대 취지"),
            FurtherReview(chunk_id="law_patent#9", why="edition_unknown"),
        ],
        search_log=[
            SearchLogEntry(
                source_kind="statute",
                index_version="law-idx-v2",
                as_of=date(2026, 1, 1),
                queries=2,
                hits=7,
                skipped_unverified_edition=1,
                skipped_unknown_date=0,
            )
        ],
    )
    again = LegalEvidenceBundle.model_validate(b.model_dump(mode="json"))
    assert again == b


def test_묶음_unit_id_꼴이_틀리면_거부_null은_통과():
    data = bundle().model_dump(mode="json")
    with pytest.raises(ValidationError, match="unit_id 꼴"):
        LegalEvidenceBundle.model_validate({**data, "unit_id": "nonsense"})
    # 법률 질문 흐름은 판단 단위가 없다
    # unit_id를 빼도 oa 흐름 칸은 그대로 통과 (판단 단위 없이 거절이유만 가리킬 수 있다)
    assert LegalEvidenceBundle.model_validate({**data, "unit_id": None}).unit_id is None


# ---------- 질문 ----------


def test_질문_text는_비지_않음():
    with pytest.raises(ValidationError):
        question(text="  ")


@pytest.mark.parametrize("kinds", [[], ["statute", "statute"]])
def test_질문_source_kinds는_비지_않고_중복_없음(kinds):
    with pytest.raises(ValidationError):
        question(source_kinds=kinds)


def test_질문_as_of와_as_of_source는_함께_있거나_함께_없음():
    with pytest.raises(ValidationError):
        question(as_of=date(2026, 1, 1), as_of_source="none")
    with pytest.raises(ValidationError):
        question(as_of=None, as_of_source="user_text")
    for src in ("user_text", "user_condition", "oa_dispatch_date"):
        assert question(as_of=date(2026, 1, 1), as_of_source=src).as_of_source == src


def test_질문_article_refs는_안_주면_빈_목록():
    data = question().model_dump(mode="json")
    del data["article_refs"]
    assert LegalQuestion.model_validate(data).article_refs == []


def test_질문_안에_oa_id를_두면_거부():
    # oa_id·rejection은 질문 안이 아니라 묶음 맨 위 칸 (DB 거르기 컬럼)
    with pytest.raises(ValidationError):
        question(oa_id="oa_1")


# ---------- oa_id·rejection·unit_id (묶음 맨 위) ----------


def test_oa_rejection_질문은_oa_id와_rejection이_둘_다_있어야_함():
    with pytest.raises(ValidationError, match="oa_id"):
        bundle(oa_id=None, rejection=None, unit_id=None)
    with pytest.raises(ValidationError, match="oa_id"):
        bundle(rejection=None)
    with pytest.raises(ValidationError, match="oa_id"):
        bundle(oa_id=None)


def test_user_question이면_oa_id_rejection_unit_id는_null():
    q = question(source="user_question")
    ok = bundle(question=q, oa_id=None, rejection=None, unit_id=None)
    assert ok.oa_id is None and ok.rejection is None
    with pytest.raises(ValidationError):
        bundle(question=q, oa_id="oa_1", rejection=1, unit_id=None)
    with pytest.raises(ValidationError):
        bundle(question=q, oa_id=None, rejection=None, unit_id="oa_1:29-2:c1")


def test_rejection은_1부터():
    with pytest.raises(ValidationError):
        bundle(rejection=0)


def test_unit_id는_oa_id로_시작해야_함():
    with pytest.raises(ValidationError, match="unit_id"):
        bundle(oa_id="oa_2")
    assert bundle(oa_id="oa_1").unit_id == "oa_1:29-2:c1"


def test_묶음_맨_위_as_of_칸은_없음():
    assert "as_of" not in LegalEvidenceBundle.model_fields
    with pytest.raises(ValidationError):
        bundle(as_of=date(2026, 1, 1))


# ---------- 검토 판정·직접 검토 필요 ----------


def test_Review_reason은_비지_않음_verdict_네_값():
    with pytest.raises(ValidationError):
        Review(verdict="supported", reason=" ")
    assert {v.value for v in type(Review(verdict="supported", reason="ok").verdict)} == {
        "supported", "partial", "not_supported", "undetermined",
    }  # fmt: skip


@pytest.mark.parametrize("verdict", ["partial", "not_supported", "undetermined"])
def test_review가_supported_아니면_needs_human_review_필수(verdict):
    r = Review(verdict=verdict, reason="이유")
    with pytest.raises(ValidationError, match="needs_human_review"):
        claim(review=r)
    assert claim(review=r, flags=["needs_human_review"]).review.verdict == verdict


def test_review가_supported면_flag_없이_통과():
    assert claim(review=Review(verdict="supported", reason="뒷받침")).review is not None


def test_speaker_unknown_근거가_있으면_needs_human_review_필수():
    unk = source(kind="precedent", edition=None, speaker="unknown")
    with pytest.raises(ValidationError, match="needs_human_review"):
        claim(sources=[unk])
    assert claim(sources=[unk], flags=["needs_human_review"]).sources[0].speaker == "unknown"


# ---------- 더 볼 조각·검색 기록 ----------


def test_FurtherReview_chunk_id_비지_않음_why_다섯_값():
    with pytest.raises(ValidationError):
        FurtherReview(chunk_id=" ", why="other_edition")
    for why in (
        "opposite_holding", "edition_unknown", "other_edition",
        "edition_out_of_scope", "not_used_candidate",
    ):  # fmt: skip
        assert FurtherReview(chunk_id="c#1", why=why).note is None
    with pytest.raises(ValidationError):
        FurtherReview(chunk_id="c#1", why="whatever")


def test_SearchLogEntry_개수는_음수_불가_기본_0():
    e = SearchLogEntry(source_kind="precedent", queries=1, hits=0)
    assert (e.skipped_unverified_edition, e.skipped_unknown_date) == (0, 0)
    for name in ("queries", "hits", "skipped_unverified_edition", "skipped_unknown_date"):
        data = {"source_kind": "precedent", "queries": 1, "hits": 0, name: -1}
        with pytest.raises(ValidationError):
            SearchLogEntry(**data)


# ---------- 리뷰 반영 (PR #176) ----------

NOT_FOUND = Status(value="not_found_in_scope", searched_scope="특허법 조문")


def test_LegalClaim_물려받은_evidence는_비어_있어야_함():
    # 실제 근거는 sources[].evidence 한 곳
    with pytest.raises(ValidationError, match="evidence"):
        LegalClaim(
            status=NOT_FOUND,
            no=1,
            text="t",
            sources=[],
            evidence=[Evidence(document_id="d")],
        )


def test_근거가_있고_review가_없으면_needs_human_review_필수():
    with pytest.raises(ValidationError, match="review"):
        claim(review=None, flags=[])


def test_근거가_있고_review가_없어도_flag가_있으면_통과():
    c = claim(review=None, flags=["needs_human_review"])
    assert c.review is None


def test_review가_있으면_supported일_때_flag_없이_통과():
    c = claim(review=Review(verdict="supported", reason="뒷받침"), flags=[])
    assert c.flags == []


def test_근거_0개_주장은_review_없이_flag_없이_통과():
    c = claim(sources=[], status=NOT_FOUND)
    assert c.review is None


@pytest.mark.parametrize("kind", ["statute", "guideline", "precedent", "trial"])
@pytest.mark.parametrize("raw_text", [None, "", "  "])
def test_confirmed_근거는_raw_text_필수(kind, raw_text):
    ev = Evidence(
        document_id="d",
        location="제29조",
        raw_text=raw_text,
        edition="2024-01-01 시행",
    )
    with pytest.raises(ValidationError, match="raw_text"):
        source(kind=kind, evidence=ev)


def test_confirmed가_아니면_raw_text_없이_통과():
    ev = Evidence(document_id="d", edition=None)
    assert source(evidence=ev, status=UNKNOWN_EDITION).evidence.raw_text is None


def test_못_찾음인데_판본_몰라_뺀_조각이_있으면_거부():
    # 못 찾음 != 없음: 뺀 조각이 있으면 unverified(edition_unknown)
    for field in ("skipped_unverified_edition", "skipped_unknown_date"):
        log = SearchLogEntry(source_kind="statute", queries=1, hits=0, **{field: 2})
        with pytest.raises(ValidationError, match="skipped"):
            bundle(claims=[], status=NOT_FOUND, search_log=[log])


def test_뺀_조각이_있으면_unverified로_통과():
    log = SearchLogEntry(source_kind="statute", queries=1, hits=0, skipped_unverified_edition=2)
    b = bundle(claims=[], status=UNKNOWN_EDITION, search_log=[log])
    assert b.status.reason == "edition_unknown"


def test_뺀_조각이_없으면_못_찾음_통과():
    log = SearchLogEntry(source_kind="statute", queries=1, hits=0)
    assert bundle(claims=[], status=NOT_FOUND, search_log=[log]).claims == []


def test_FurtherReview는_index_version_칸이_있다():
    f = FurtherReview(chunk_id="c#1", why="other_edition", index_version="law-idx-v2")
    assert f.index_version == "law-idx-v2"
    assert FurtherReview(chunk_id="c#1", why="other_edition").index_version is None
