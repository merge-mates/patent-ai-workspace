"""법률 질문 대화 저장소(메모리) 테스트. 기대값은 이슈 #29 계획 task-2."""

from datetime import timedelta

import pytest

from patent_ai.core.f2_legal_research.chat_store import ChatNotFound, InMemoryLegalChatStore
from tests.core.f2.chat_fakes import NOW, UNVERIFIED, bundle, question, source


def test_만들면_lc_로_시작하는_ID와_빈_턴으로_되읽힌다():
    store = InMemoryLegalChatStore()
    chat = store.create("c_1", NOW)
    assert chat.chat_id.startswith("lc_")
    got = store.get(chat.chat_id)
    assert got is not None
    assert (got.case_id, got.created_at, got.turns) == ("c_1", NOW, [])
    assert got.last_question is None
    assert store.create(None, NOW).case_id is None


def test_없는_대화는_get이_None_add_turn은_ChatNotFound():
    store = InMemoryLegalChatStore()
    assert store.get("lc_없음") is None
    with pytest.raises(ChatNotFound):
        store.add_turn("lc_없음", question(), False, bundle(), NOW)
    assert issubclass(ChatNotFound, KeyError)


def test_턴_번호는_1부터_이어지고_순서대로_되읽힌다():
    store = InMemoryLegalChatStore()
    chat = store.create(None, NOW)
    t1 = store.add_turn(chat.chat_id, question("첫 질문"), False, bundle("lb_1"), NOW)
    t2 = store.add_turn(
        chat.chat_id, question("둘째"), True, bundle("lb_2"), NOW + timedelta(minutes=1)
    )
    assert (t1.no, t2.no) == (1, 2)
    got = store.get(chat.chat_id)
    assert [t.no for t in got.turns] == [1, 2]
    assert [t.scope_changed for t in got.turns] == [False, True]
    assert got.turns[1].bundle.bundle_id == "lb_2"
    assert got.last_question.text == "둘째"
    assert got.turns[1].created_at == NOW + timedelta(minutes=1)


def test_대화마다_턴_번호가_따로_센다():
    store = InMemoryLegalChatStore()
    a, b = store.create(None, NOW), store.create(None, NOW)
    store.add_turn(a.chat_id, question(), False, bundle(), NOW)
    assert store.add_turn(b.chat_id, question(), False, bundle(), NOW).no == 1


def test_prior_evidence는_확인된_근거의_조각ID를_순서대로_중복없이():
    store = InMemoryLegalChatStore()
    chat = store.create(None, NOW)
    # 1턴: #12, #7 확인됨 + #99는 확인되지 않음(뺀다) + 조각 ID 없는 근거(뺀다)
    store.add_turn(
        chat.chat_id,
        question(),
        False,
        bundle(
            "lb_1",
            ("law_patent#12", "law_patent#7"),
            extra_sources=[
                source("law_patent#99", UNVERIFIED),
                source(None),
            ],
        ),
        NOW,
    )
    # 2턴: #7 중복, #3 새로
    store.add_turn(chat.chat_id, question(), False, bundle("lb_2", ("law_patent#7", "x#3")), NOW)
    assert store.get(chat.chat_id).prior_evidence == ["law_patent#12", "law_patent#7", "x#3"]
