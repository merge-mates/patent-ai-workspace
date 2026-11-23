"""PostgresLegalChatStore 실제 DB 저장·읽기 (make test-db). 끝에 되돌린다 (이슈 #29 task-2)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from patent_ai.core.cases.store import CaseNotFoundError, NewDocument
from patent_ai.core.cases.store_pg import PostgresCaseAppStore
from patent_ai.core.f2_legal_research.chat_store import ChatCorrupt, ChatNotFound
from patent_ai.core.f2_legal_research.chat_store_pg import PostgresLegalChatStore
from patent_ai.settings import get_settings
from tests.core.f2.chat_fakes import NOW, UNVERIFIED, bundle, question, source

pytestmark = pytest.mark.db


@pytest.fixture
def session():
    engine = create_engine(get_settings().database_url)
    conn = engine.connect()
    outer = conn.begin()
    s = sessionmaker(bind=conn, join_transaction_mode="create_savepoint")()
    try:
        yield s
    finally:
        s.close()
        outer.rollback()
        conn.close()
        engine.dispose()


def test_만들면_lc_로_시작하는_ID와_빈_턴으로_되읽힌다(session):
    store = PostgresLegalChatStore(session)
    chat = store.create(None, NOW)
    assert chat.chat_id.startswith("lc_")
    got = store.get(chat.chat_id)
    assert (got.case_id, got.created_at, got.turns) == (None, NOW, [])
    assert got.last_question is None


def test_사건에_붙여_만들_수_있고_없는_사건은_거절된다(session):
    created = PostgresCaseAppStore(session).create_case(
        NewDocument(
            path="work/uploads/db_chat.pdf",
            sha256="db_chat_" + "a" * 20,
            received_at=datetime(2099, 1, 1, tzinfo=UTC),
        )
    )
    store = PostgresLegalChatStore(session)
    assert store.get(store.create(created.case_id, NOW).chat_id).case_id == created.case_id
    with pytest.raises(CaseNotFoundError):
        store.create("c_없는사건", NOW)


def test_없는_대화는_get이_None_add_turn은_ChatNotFound(session):
    store = PostgresLegalChatStore(session)
    assert store.get("lc_없음") is None
    with pytest.raises(ChatNotFound):
        store.add_turn("lc_없음", question(), False, bundle(), NOW)


def test_턴_번호는_1부터_이어지고_순서대로_되읽힌다(session):
    store = PostgresLegalChatStore(session)
    chat = store.create(None, NOW)
    t1 = store.add_turn(chat.chat_id, question("첫 질문"), False, bundle("lb_1"), NOW)
    later = NOW + timedelta(minutes=1)
    t2 = store.add_turn(chat.chat_id, question("둘째"), True, bundle("lb_2"), later)
    assert (t1.no, t2.no) == (1, 2)
    got = store.get(chat.chat_id)
    assert [t.no for t in got.turns] == [1, 2]
    assert [t.scope_changed for t in got.turns] == [False, True]
    assert got.turns[1].bundle == bundle("lb_2")  # 묶음이 그대로 되읽힘
    assert got.turns[1].question.text == "둘째"
    assert got.turns[1].created_at == later
    assert got.last_question.text == "둘째"


def test_prior_evidence는_확인된_근거의_조각ID를_순서대로_중복없이(session):
    store = PostgresLegalChatStore(session)
    chat = store.create(None, NOW)
    extra = [source("law_patent#99", UNVERIFIED), source(None)]
    first = bundle("lb_1", ("law_patent#12", "law_patent#7"), extra_sources=extra)
    store.add_turn(chat.chat_id, question(), False, first, NOW)
    store.add_turn(chat.chat_id, question(), False, bundle("lb_2", ("law_patent#7", "x#3")), NOW)
    assert store.get(chat.chat_id).prior_evidence == ["law_patent#12", "law_patent#7", "x#3"]


def test_저장된_묶음을_못_읽으면_빈_대화로_넘기지_않고_ChatCorrupt(session):
    store = PostgresLegalChatStore(session)
    chat = store.create(None, NOW)
    store.add_turn(chat.chat_id, question(), False, bundle(), NOW)
    session.execute(
        text("UPDATE legal_chat_turns SET bundle = '{\"틀린\": 1}'::jsonb WHERE chat_id = :c"),
        {"c": chat.chat_id},
    )
    with pytest.raises(ChatCorrupt):
        store.get(chat.chat_id)


def test_대화를_지우면_턴도_같이_지워진다(session):
    store = PostgresLegalChatStore(session)
    chat = store.create(None, NOW)
    store.add_turn(chat.chat_id, question(), False, bundle(), NOW)
    session.execute(text("DELETE FROM legal_chats WHERE chat_id = :c"), {"c": chat.chat_id})
    n = session.execute(
        text("SELECT count(*) FROM legal_chat_turns WHERE chat_id = :c"), {"c": chat.chat_id}
    ).scalar()
    assert n == 0
