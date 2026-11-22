"""F2 법률 질문 하나 -> 근거 묶음 (모델 없음, 네트워크·DB 없음). 계획 m3-i2-29a task-1."""

from datetime import date

import pytest

from patent_ai.core.f2_legal_research.chat import ChatAsk, answer_question, next_question
from patent_ai.core.f2_legal_research.tools import LawPool
from patent_ai.core.schemas.common import Flag, Origin, StatusValue, UnverifiedReason
from patent_ai.core.schemas.legal_evidence import (
    AsOfSource,
    FurtherReviewWhy,
    LegalSourceKind,
    QuestionSource,
)
from patent_ai.retrieval.contract import get_searcher
from patent_ai.retrieval.repository import InMemoryChunkRepository
from patent_ai.retrieval.schemas import Edition
from tests.core.f2 import fakes
from tests.core.f2.fakes import IV, NEW_DOC, OLD_DOC, law_chunk

S, G, P, T = (
    LegalSourceKind.STATUTE,
    LegalSourceKind.GUIDELINE,
    LegalSourceKind.PRECEDENT,
    LegalSourceKind.TRIAL,
)
TODAY = date(2024, 1, 1)


def _answer(text, *, as_of=None, kinds=None, prior=(), repo=None):
    repo = repo or fakes.repo()
    pool = LawPool.load(repo, IV)
    searcher = get_searcher("bm25", repo, {"index_version": IV, "tokenizer": "char_bigram"})
    ask = {"text": text, **({"as_of": as_of} if as_of else {})}
    if kinds is not None:
        ask["source_kinds"] = kinds
    q, _ = next_question(None, ChatAsk(**ask))
    return answer_question(
        q,
        bundle_id="lb:chat1:1",
        pool=pool,
        searcher=searcher,
        checked_on=TODAY,
        prior_evidence=list(prior),
        search_k=3,
    )


# --- next_question: 조건 물려받기 ---


def test_첫_질문은_현행_전부_찾기이고_scope_changed가_아니다():
    q, changed = next_question(None, ChatAsk(text="특허법 제29조제2항이 뭔가요"))
    assert q.source == QuestionSource.USER_QUESTION
    assert (q.as_of, q.as_of_source) == (None, AsOfSource.NONE)
    assert set(q.source_kinds) == {S, G, P, T}
    assert q.article_refs == ["특허법 제29조제2항"]
    assert changed is False


def test_시점을_주면_user_condition이고_빠지면_앞_질문을_물려받는다():
    q1, _ = next_question(None, ChatAsk(text="첫 질문", as_of=date(2018, 5, 4)))
    assert (q1.as_of, q1.as_of_source) == (date(2018, 5, 4), AsOfSource.USER_CONDITION)
    q2, changed = next_question(q1, ChatAsk(text="이어서 묻기"))
    assert (q2.as_of, q2.as_of_source) == (date(2018, 5, 4), AsOfSource.USER_CONDITION)
    assert q2.source_kinds == q1.source_kinds and changed is False


def test_as_of를_null로_주면_현행으로_덮고_scope_changed():
    q1, _ = next_question(None, ChatAsk(text="첫 질문", as_of=date(2018, 5, 4)))
    q2, changed = next_question(q1, ChatAsk(text="현행으로", as_of=None))
    assert (q2.as_of, q2.as_of_source) == (None, AsOfSource.NONE)
    assert changed is True


def test_시점을_바꾸면_scope_changed():
    q1, _ = next_question(None, ChatAsk(text="첫 질문", as_of=date(2018, 5, 4)))
    q2, changed = next_question(q1, ChatAsk(text="다른 시점", as_of=date(2021, 1, 1)))
    assert q2.as_of == date(2021, 1, 1) and changed is True


def test_자료_유형은_집합이_달라야_scope_changed이고_빈_목록은_전부():
    q1, _ = next_question(None, ChatAsk(text="첫 질문", source_kinds=[S, G]))
    assert q1.source_kinds == [S, G]
    _, same = next_question(q1, ChatAsk(text="순서만 다름", source_kinds=[G, S]))
    assert same is False
    q3, changed = next_question(q1, ChatAsk(text="전부", source_kinds=[]))
    assert set(q3.source_kinds) == {S, G, P, T} and changed is True


def test_빈_질문_글은_받지_않는다():
    with pytest.raises(ValueError):
        ChatAsk(text="   ")


# --- answer_question ---


def test_조문_번호_질문은_그_조문의_확인된_근거_하나와_사람_검토_표시():
    b = _answer("특허법 제29조제2항이 뭔가요")
    assert b.status.value == StatusValue.CONFIRMED
    assert b.unit_id is None and b.oa_id is None and b.rejection is None
    assert b.origin == Origin.AI_GENERATED and b.checked_on == TODAY
    (claim,) = b.claims
    assert claim.review is None and Flag.NEEDS_HUMAN_REVIEW in claim.flags
    src = claim.sources[0]
    assert src.evidence.chunk_id == f"{IV}:{NEW_DOC}:290002"  # 기준일 없음 -> 오늘(현행) 판
    assert claim.text == f"질문에서 찾은 조문: 특허법 제29조제2항 ({src.evidence.edition})"
    assert src.evidence.raw_text == fakes.TEXT_292_NEW


def test_질문의_시점을_기준일로_쓴다():
    b = _answer("특허법 제29조제2항", as_of=date(2018, 5, 4))
    assert b.claims[0].sources[0].evidence.chunk_id == f"{IV}:{OLD_DOC}:290002"
    assert b.question.as_of == date(2018, 5, 4)


def test_번호_없는_질문은_BM25_상위_조문을_찾는다():
    b = _answer("통상의 기술자 진보성", kinds=[S])
    assert b.claims and b.claims[0].sources[0].evidence.chunk_id == f"{IV}:{NEW_DOC}:290002"
    assert all(s.source_kind == S for c in b.claims for s in c.sources)
    assert b.search_log[0].queries == 1 and b.search_log[0].hits == len(b.claims)


def test_판본_모름_조각만_걸리면_unverified_edition_unknown():
    b = _answer("특허법 제29조제2항", as_of=date(2010, 1, 1))
    assert b.claims == []
    assert (b.status.value, b.status.reason) == (
        StatusValue.UNVERIFIED,
        UnverifiedReason.EDITION_UNKNOWN,
    )


def test_어느_판에도_없는_조문은_조회_범위_내_없음과_찾아본_범위():
    b = _answer("특허법 제30조제1항", kinds=[S])
    assert b.claims == [] and b.status.value == StatusValue.NOT_FOUND_IN_SCOPE
    assert "특허법 제30조제1항" in b.status.searched_scope


def test_법령을_안_고르면_법령을_찾지_않는다():
    b = _answer("특허법 제29조제2항", kinds=[G])
    assert b.claims == []
    assert [e.source_kind for e in b.search_log] == [G]
    assert b.status.value == StatusValue.UNVERIFIED


def test_심사기준_판례_심결은_body_missing으로만_기록한다():
    b = _answer("특허법 제29조제2항")
    logs = {e.source_kind: e for e in b.search_log}
    for kind in (G, P, T):
        assert (logs[kind].queries, logs[kind].hits) == (0, 0)
        assert logs[kind].status.reason == UnverifiedReason.BODY_MISSING
    assert logs[S].hits == 1


@pytest.mark.parametrize(
    "text",
    ["특허법 제29조제2항", "통상의 기술자 진보성", "특허법 제42조제4항"],
)
def test_주장_글에_사건_적용_판단_문장이_없다(text):
    b = _answer(text)
    assert b.claims
    for c in b.claims:
        assert not any(w in c.text for w in ("적용", "해당한다", "해당합니다", "위반"))


def test_앞_조각이_기준일_판이_아니면_further_review():
    old_chunk = f"{IV}:{OLD_DOC}:290002"
    new_chunk = f"{IV}:{NEW_DOC}:290002"
    b = _answer("특허법 제29조제2항", prior=[old_chunk, new_chunk])
    assert [(f.chunk_id, f.why) for f in b.further_review] == [
        (old_chunk, FurtherReviewWhy.EDITION_OUT_OF_SCOPE)
    ]


def test_주장이_없으면_경고를_한_번_남긴다(caplog):
    _answer("특허법 제30조제1항", kinds=[S])
    assert len([r for r in caplog.records if "주장 0개" in r.getMessage()]) == 1


def test_판본_모름_조각이_섞인_검색은_없음으로_내지_않는다():
    unknown = law_chunk(
        "특허법_1003_20250101",
        500001,
        "제50조제1항",
        "판본 모름 가짜 글",
        Edition(status="unverified"),
    )
    b = _answer("판본 모름 가짜 글", kinds=[S], repo=InMemoryChunkRepository({"law": [unknown]}))
    assert b.claims == []
    assert b.status.value == StatusValue.UNVERIFIED
