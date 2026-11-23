"""F2 task-d3: 심사기준·판례·심결 검색 연결 (지어낸 조각, 모델·DB 없음)."""

from datetime import date

import pytest

from patent_ai.core.f2_legal_research.run import load_f2_settings
from patent_ai.core.f2_legal_research.source_search import (
    build_searcher,
    candidate_reviews,
    search_sources,
)
from patent_ai.core.f2_legal_research.tools import LawPool
from patent_ai.core.schemas.common import StatusValue, UnverifiedReason
from patent_ai.core.schemas.legal_evidence import LegalSourceKind, Speaker, TextKind
from patent_ai.retrieval.repository import InMemoryChunkRepository
from patent_ai.retrieval.schemas import (
    Chunk,
    Edition,
    Location,
    SearchHit,
    SearchResult,
    SearchScope,
)

IV = "law-idx-v3"
G1 = Edition(
    status="confirmed",
    effective_from=date(2018, 1, 1),
    effective_to=date(2018, 4, 23),
    label="예규 101",
)
G2 = Edition(
    status="confirmed",
    effective_from=date(2018, 8, 1),
    effective_to=date(2023, 3, 21),
    label="예규 125",
)
NA = Edition(status="not_applicable")
Q = "진보성 판단 통상의 기술자 용이하게 발명"


def _chunk(cid, doc, kind, source, text, edition, label, **extra) -> Chunk:
    return Chunk(
        chunk_id=f"{IV}:{cid}",
        index_version=IV,
        doc_id=doc,
        chunk_kind=kind,
        source_kind=source,
        location=Location(kind="page", start=1, end=1, label=label),
        edition=edition,
        text=text,
        **extra,
    )


def _guide(cid, edition, text="진보성 판단 통상의 기술자가 용이하게 발명할 수 있는지"):
    return _chunk(cid, f"심사기준_{cid}", "guideline", "guideline", text, edition, "1쪽 (3부 3장)")


def _case(cid, source, kind, text, decided_on, speaker, **extra):
    return _chunk(
        cid, f"{source}_{cid}", kind, source, text, NA, "문단", decided_on=decided_on,
        speaker=speaker, attrs={"법원명": "대법원"}, **extra,
    )  # fmt: skip


def _pool(*extra: Chunk) -> LawPool:
    repo = InMemoryChunkRepository({"law": list(extra)})
    return LawPool.load(repo, IV)


def _all() -> list[Chunk]:
    P, T = "precedent", "trial"
    return [
        _guide("g1", G1),
        _guide("g2", G2),
        _case("p1", P, "judgment_summary", "진보성 판단 통상 기술자 용이",
            date(2010, 5, 1), "court"),
        _case("p2", P, "judgment", "진보성 원고의 주장 통상의 기술자", date(2012, 5, 1), "party"),
        _case("p3", P, "judgment", "진보성 판단 통상 기술자 이후 판결", date(2021, 5, 1), "court"),
        _case("p4", P, "judgment", "진보성 통상의 기술자 날짜 모름", None, "unknown"),
        _case("t1", T, "judgment", "진보성 통상의 기술자 심결", date(2015, 1, 1), "court"),
    ]  # fmt: skip


CHECKED = date(2026, 11, 23)


def _run(pool, as_of, query=Q):
    st = load_f2_settings()
    found = search_sources(
        pool, build_searcher(pool, st.tokenizer, st.bm25), query, as_of, st.source_search_k, CHECKED
    )
    return {r.log.source_kind: r for r in found}


def test_심사기준은_기준일_판만_나온다():
    got = _run(_pool(*_all()), date(2018, 9, 1))[LegalSourceKind.GUIDELINE]
    assert [s.evidence.chunk_id for s in got.sources] == [f"{IV}:g2"]
    assert got.log.hits == 1 and got.log.queries == 1
    assert got.log.status.value == StatusValue.CONFIRMED


def test_판_사이_빈_기간은_없음이_아니라_edition_unknown():
    got = _run(_pool(*_all()), date(2018, 6, 1))[LegalSourceKind.GUIDELINE]  # 2018.4.24~7.31
    assert got.sources == ()
    assert (got.log.status.value, got.log.status.reason) == (
        StatusValue.UNVERIFIED,
        UnverifiedReason.EDITION_UNKNOWN,
    )


def test_가장_이른_판보다_앞선_기준일도_edition_unknown():
    got = _run(_pool(*_all()), date(2010, 1, 1))[LegalSourceKind.GUIDELINE]
    assert got.log.status.reason == UnverifiedReason.EDITION_UNKNOWN


def test_심사기준_조각이_0개면_body_missing():
    got = _run(_pool(*_all()[2:]), date(2018, 9, 1))[LegalSourceKind.GUIDELINE]
    assert got.log.status.reason == UnverifiedReason.BODY_MISSING


def test_기준일_판은_있는데_안_걸리면_조회_범위_내_없음():
    got = _run(_pool(*_all()), date(2018, 9, 1), "전혀 다른 말 xyz")[LegalSourceKind.GUIDELINE]
    assert got.log.status.value == StatusValue.NOT_FOUND_IN_SCOPE


def test_판례는_선고일이_기준일_뒤면_빠지고_날짜_모름은_센다():
    got = _run(_pool(*_all()), date(2018, 9, 1))[LegalSourceKind.PRECEDENT]
    ids = {s.evidence.chunk_id.split(":")[-1] for s in got.sources}
    assert ids == {"p1", "p2"}  # p3(2021)·p4(날짜 모름) 빠짐
    assert got.log.skipped_unknown_date == 1


def test_판례_요지_전문과_판단_당사자를_남긴다():
    got = _run(_pool(*_all()), date(2018, 9, 1))[LegalSourceKind.PRECEDENT]
    by = {s.evidence.chunk_id.split(":")[-1]: s for s in got.sources}
    assert (by["p1"].text_kind, by["p1"].speaker) == (TextKind.SUMMARY, Speaker.COURT)
    assert (by["p2"].text_kind, by["p2"].speaker) == (TextKind.FULL, Speaker.PARTY)
    assert by["p1"].decided_on == date(2010, 5, 1) and by["p1"].court == "대법원"


def test_심결은_심결만_나온다():
    got = _run(_pool(*_all()), date(2018, 9, 1))[LegalSourceKind.TRIAL]
    assert [s.source_kind for s in got.sources] == [LegalSourceKind.TRIAL]


def test_기준일을_모르면_판례_심결은_검색하지_않는다():
    got = _run(_pool(*_all()), None)
    for kind in (LegalSourceKind.PRECEDENT, LegalSourceKind.TRIAL):
        assert got[kind].log.queries == 0
        assert got[kind].log.status.reason == UnverifiedReason.INPUT_UNVERIFIED


def test_질의의_되풀이_낱말은_한_번만_센다():
    # 되풀이한 질의의 점수가 한 번 쓴 것과 같다. 끈 검색기는 점수가 커진다
    pool = _pool(*_all())
    st = load_f2_settings()

    def score(bm25, query):
        s = build_searcher(pool, st.tokenizer, bm25)
        return s.search(query, "law", "bm25", 3, as_of=date(2018, 9, 1)).hits[0].score

    assert score(st.bm25, "진보성 " * 5) == pytest.approx(score(st.bm25, "진보성 "))
    off = {**st.bm25, "unique_query_terms": False}
    assert score(off, "진보성 " * 5) > score(off, "진보성 ")


def test_0개인데_날짜_모름으로_건너뛴_판례가_있으면_확인되지_않음():
    late = _case("p3", "precedent", "judgment", "진보성 판단 이후 판결", date(2021, 5, 1), "court")
    unknown = _case("p4", "precedent", "judgment", "진보성 날짜 모름", None, "unknown")
    got = _run(_pool(late, unknown), date(2018, 9, 1))[LegalSourceKind.PRECEDENT]
    assert got.sources == () and got.log.skipped_unknown_date == 1
    assert (got.log.status.value, got.log.status.reason) == (
        StatusValue.UNVERIFIED,
        UnverifiedReason.EDITION_UNKNOWN,
    )


def test_0개인데_판본_모름으로_건너뛴_심사기준이_있으면_확인되지_않음():
    unknown = _guide("g9", Edition(status="unverified"))
    pool = _pool(_guide("g2", G2), unknown)
    got = _run(pool, date(2018, 9, 1), "전혀 다른 말 xyz")[LegalSourceKind.GUIDELINE]
    assert got.sources == () and got.log.skipped_unverified_edition == 1
    assert got.log.status.reason == UnverifiedReason.EDITION_UNKNOWN


# --- 후보의 출처와 출처 확인 (#28 28a) ---


def test_후보에_원문_위치_판본_선고일이_source로_남는다():
    found = list(_run(_pool(*_all()), date(2018, 9, 1)).values())
    by = {f.chunk_id.split(":")[-1]: f.source for f in candidate_reviews(found)}
    assert set(by) == {"g2", "p1", "p2", "t1"}
    guide, case = by["g2"], by["p2"]
    assert guide.evidence.location == "1쪽 (3부 3장)" and "2018-08-01" in guide.evidence.edition
    assert guide.evidence.raw_text.startswith("진보성 판단")
    assert (case.decided_on, case.text_kind, case.speaker) == (
        date(2012, 5, 1), TextKind.FULL, Speaker.PARTY,
    )  # fmt: skip


class _FixedSearcher:
    """정한 조각을 그대로 내는 검색기: 색인과 어긋난 결과가 와도 출처 확인이 막는지 본다."""

    def __init__(self, *chunks: Chunk):
        self.chunks = chunks

    def search(self, query, corpus, mode, k, **kw):
        hits = [
            SearchHit(**c.model_dump(exclude={"embedding"}), score=1.0, rank=i)
            for i, c in enumerate(self.chunks, 1)
        ]
        scope = SearchScope(k=k)
        return SearchResult(corpus=corpus, index_version=IV, mode=mode, scope=scope, hits=hits)


def _precedents(searcher):
    as_of = date(2018, 9, 1)
    got = search_sources(
        _pool(*_all()), searcher, Q, as_of, 3, CHECKED, [LegalSourceKind.PRECEDENT]
    )
    assert [r.log.source_kind for r in got] == [LegalSourceKind.PRECEDENT]
    return got[0]


def test_색인과_다른_글_미래_판결_날짜_모름은_출처_확인에서_빠진다(caplog):
    by = {c.chunk_id.split(":")[-1]: c for c in _all()}
    fake = by["p2"].model_copy(update={"text": "지어낸 판결 글"})
    got = _precedents(_FixedSearcher(by["p1"], fake, by["p3"], by["p4"]))
    assert [s.evidence.chunk_id for s in got.sources] == [f"{IV}:p1"]
    assert got.log.hits == 1 and got.log.status.value == StatusValue.CONFIRMED
    assert "출처 확인" in caplog.text


def test_걸린_것이_모두_출처_확인에서_빠지면_evidence_rejected():
    later = next(c for c in _all() if c.chunk_id.endswith(":p3"))
    got = _precedents(_FixedSearcher(later))
    assert got.sources == () and got.log.hits == 0 and got.log.queries == 1
    assert got.log.status.reason == UnverifiedReason.EVIDENCE_REJECTED
