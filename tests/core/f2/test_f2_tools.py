"""F2 task-2: 검색 도구와 출처 확인 (코드, 모델·DB 없음)."""

from datetime import date

from patent_ai.core.f2_legal_research.refs import article_ref
from patent_ai.core.f2_legal_research.tools import (
    check_source,
    get_article,
    search_article,
    search_guideline,
    search_precedent,
)
from patent_ai.core.schemas.common import StatusValue, UnverifiedReason
from patent_ai.core.schemas.legal_evidence import LegalSourceKind
from patent_ai.retrieval.contract import get_searcher
from patent_ai.retrieval.schemas import Edition
from tests.core.f2 import fakes
from tests.core.f2.fakes import IV, NEW, NEW_DOC, OLD_DOC, law_chunk

R292 = article_ref("29-2")


def test_기준일에_시행_중인_판_조각을_고른다():
    old = get_article(fakes.repo(), IV, R292, date(2018, 5, 4))
    new = get_article(fakes.repo(), IV, R292, date(2020, 5, 4))
    assert old.chunk.doc_id == OLD_DOC and new.chunk.doc_id == NEW_DOC
    assert new.status.value == StatusValue.CONFIRMED and "제29조제2항" in new.status.checked
    assert (new.log.source_kind, new.log.hits, new.log.queries) == (LegalSourceKind.STATUTE, 1, 1)


def test_시행령_조각은_특허법_조회에_섞이지_않는다():
    got = get_article(fakes.repo(), IV, R292, date(2020, 5, 4))
    assert got.log.hits == 1 and not got.chunk.doc_id.startswith("특허법_시행령")


def test_다른_판만_있고_그날_판이_색인에_없으면_없음이_아니라_확인되지_않음(caplog):
    # 가장 이른 판(2015)보다 앞선 날: 그날 글을 모를 뿐 조문이 없는 것이 아니다
    got = get_article(fakes.repo(), IV, R292, date(2010, 1, 1))
    assert got.chunk is None
    assert (got.status.value, got.status.reason) == (
        StatusValue.UNVERIFIED,
        UnverifiedReason.EDITION_UNKNOWN,
    )
    assert "색인에 없음" in caplog.text


def test_어느_판에도_없는_조문은_조회_범위_내_없음():
    got = get_article(fakes.repo(), IV, article_ref("30-1"), date(2020, 5, 4))
    assert got.chunk is None and got.status.value == StatusValue.NOT_FOUND_IN_SCOPE
    assert "모든 판" in got.status.searched_scope and "2020-05-04" in got.status.searched_scope


def test_판본_모름_조각만_걸리면_확인되지_않음_edition_unknown():
    unknown = law_chunk(
        "특허법_1003_20250101", 290002, "제29조제2항", "판본 모름", Edition(status="unverified")
    )
    got = get_article(fakes.repo([unknown]), IV, R292, date(2010, 1, 1))
    assert got.chunk is None
    assert (got.status.value, got.status.reason) == (
        StatusValue.UNVERIFIED,
        UnverifiedReason.EDITION_UNKNOWN,
    )
    assert got.log.skipped_unverified_edition == 1


def test_같은_날_시행판이_둘이면_충돌():
    twin = law_chunk("특허법_1009_20200101", 290002, "제29조제2항", "겹친 판", NEW)
    got = get_article(fakes.repo([twin]), IV, R292, date(2020, 5, 4))
    assert got.chunk is None and got.status.value == StatusValue.CONFLICT


def test_조문_번호_없이_질의로_찾는다():
    repo = fakes.repo()
    searcher = get_searcher("bm25", repo, {"index_version": IV, "tokenizer": "char_bigram"})
    out = search_article(searcher, "통상의 기술자 진보성", date(2020, 5, 4), 3)
    assert out.hits and out.hits[0].doc_id == NEW_DOC
    assert all(h.edition.effective_from <= date(2020, 5, 4) for h in out.hits)


def test_심사기준_판례_조각이_없으면_찾지_않고_body_missing():
    for tool, kind in (
        (search_guideline, LegalSourceKind.GUIDELINE),
        (search_precedent, LegalSourceKind.PRECEDENT),
    ):
        status, log = tool(fakes.repo(), IV, date(2020, 5, 4))
        assert (status.value, status.reason) == (
            StatusValue.UNVERIFIED,
            UnverifiedReason.BODY_MISSING,
        )
        assert (log.source_kind, log.queries, log.hits) == (kind, 0, 0)


def test_출처_확인은_있는_조각과_그대로_옮긴_글만_통과시킨다():
    repo, as_of = fakes.repo(), date(2020, 5, 4)
    cid = f"{IV}:{NEW_DOC}:290002"
    assert check_source(repo, IV, cid, "통상의  기술자", as_of)  # 공백 차이는 무시
    assert not check_source(repo, IV, f"{IV}:{NEW_DOC}:999999", "통상의 기술자", as_of)
    assert not check_source(repo, IV, cid, "지어낸 문장", as_of)
    assert not check_source(repo, IV, cid, "  ", as_of)
    assert not check_source(repo, IV, None, "통상의 기술자", as_of)
    # 기준일에 시행 중이 아닌 판은 근거가 될 수 없다
    assert not check_source(repo, IV, f"{IV}:{OLD_DOC}:290002", "구판", as_of)
