"""search()·저장소의 미리 거르기 (chunk_kinds·source_kinds·decided_on_or_before).

기대값은 tasks.md m3-i1-24 task-a2 "테스트할 경우" 목록에서 가져왔다.
지어낸 조각·메모리 저장소만 쓴다.
"""

from datetime import date

import pytest

from patent_ai.retrieval.contract import get_searcher
from patent_ai.retrieval.repository import InMemoryChunkRepository
from patent_ai.retrieval.schemas import Chunk, SearchResult, SearchScope

IV = "law-idx-v3"


def _chunk(cid, doc, kind, source_kind, edition, decided_on=None, text="신규성 판단"):
    return Chunk(
        chunk_id=f"{IV}:{doc}:{cid}",
        index_version=IV,
        doc_id=doc,
        chunk_kind=kind,
        location={"kind": "article", "label": cid},
        edition=edition,
        text=text,
        embedding=[1.0, 0.0],
        source_kind=source_kind,
        decided_on=decided_on,
        speaker="court" if decided_on else None,
    )


def _ed(frm, to=None):
    return {"status": "confirmed", "effective_from": frm, "effective_to": to}


NA = {"status": "not_applicable"}
UNV = {"status": "unverified"}

ROWS = [
    # 심사기준 같은 절 두 판 + 판본 모름 하나
    _chunk("g-old", "심사기준", "guideline", "guideline", _ed("2020-01-01", "2023-12-31")),
    _chunk("g-new", "심사기준", "guideline", "guideline", _ed("2024-01-01")),
    _chunk("g-unk", "심사기준", "guideline", "guideline", UNV),
    # 조문: 판본 모름 하나 (chunk_kinds=[guideline]이면 세지 않아야 한다)
    _chunk("a-ok", "특허법", "article", "statute", _ed("2020-01-01")),
    _chunk("a-unk", "특허법", "article", "statute", UNV),
    # 판례·심결
    _chunk("p-early", "판례1", "judgment", "precedent", NA, "2020-05-01"),
    _chunk("p-late", "판례2", "judgment", "precedent", NA, "2022-05-01"),
    _chunk("p-null", "판례3", "judgment", "precedent", NA, None),
    _chunk("t-early", "심결1", "judgment", "trial", NA, "2019-01-01"),
]


def _repo(rows=ROWS):
    return InMemoryChunkRepository({"law": list(rows)})


def _searcher(impl, rows=ROWS):
    settings = {"index_version": IV, "tokenizer": "whitespace"}
    if impl == "hybrid":
        settings["hybrid"] = {"rrf_k": 60, "weights": {"bm25": 1.0, "vector": 1.0}}
    return get_searcher(impl, _repo(rows), settings, embed=lambda q: [1.0, 0.0])


def _ids(res):
    return sorted(h.chunk_id.split(":", 2)[2] for h in res.hits)


def _short(chunks):
    return sorted(c.chunk_id.split(":", 2)[2] for c in chunks)


IMPLS = [("fake", "bm25"), ("bm25", "bm25"), ("vector", "vector"), ("hybrid", "hybrid")]


# ---- 저장소 ----


def test_저장소_자료유형으로_거른다():
    r = _repo()
    assert _short(r.chunks("law", IV, chunk_kinds=["guideline"])) == ["g-new", "g-old", "g-unk"]
    assert _short(r.chunks("law", IV, source_kinds=["trial"])) == ["t-early"]
    assert r.count_chunks("law", IV, chunk_kinds=["guideline"]) == 3
    assert r.count_chunks("law", IV, source_kinds=["precedent", "trial"]) == 4


def test_저장소_판본_모름_셈도_거른_범위로_센다():
    r = _repo()
    assert r.count_unverified_edition("law", IV) == 2
    assert r.count_unverified_edition("law", IV, chunk_kinds=["guideline"]) == 1
    assert r.count_unverified_edition("law", IV, chunk_kinds=["judgment"]) == 0


def test_저장소_선고일_이하만_남기고_당일_포함():
    r = _repo()
    day = date(2020, 5, 1)
    got = r.chunks("law", IV, chunk_kinds=["judgment"], decided_on_or_before=day)
    assert _short(got) == ["p-early", "t-early"]
    # 조문·심사기준은 날짜 거르기를 그냥 통과한다
    got = r.chunks("law", IV, chunk_kinds=["article", "guideline"], decided_on_or_before=day)
    assert len(got) == 5
    assert r.count_chunks("law", IV, chunk_kinds=["judgment"], decided_on_or_before=day) == 2


def test_저장소_날짜_모름_세기():
    r = _repo()
    assert r.count_unknown_date("law", IV) == 1
    assert r.count_unknown_date("law", IV, chunk_kinds=["article"]) == 0
    assert r.count_unknown_date("law", IV, source_kinds=["trial"]) == 0
    assert r.count_unknown_date("law", IV, doc_ids=["판례3"]) == 1


def test_저장소_빈_목록은_오류():
    r = _repo()
    for kw in ({"chunk_kinds": []}, {"source_kinds": []}):
        with pytest.raises(ValueError):
            r.chunks("law", IV, **kw)
        with pytest.raises(ValueError):
            r.count_chunks("law", IV, **kw)
        with pytest.raises(ValueError):
            r.count_unverified_edition("law", IV, **kw)
        with pytest.raises(ValueError):
            r.count_unknown_date("law", IV, **kw)


# ---- 검색기 (fake·bm25·vector·hybrid 모두) ----


@pytest.mark.parametrize(("impl", "mode"), IMPLS)
def test_심사기준_두_판_중_기준일_판만(impl, mode):
    res = _searcher(impl).search(
        "신규성", "law", mode, 10, as_of=date(2022, 6, 1), chunk_kinds=["guideline"]
    )
    assert _ids(res) == ["g-old"]
    # 판본 모름은 심사기준 것(g-unk)만 센다. 조문의 a-unk는 안 센다
    assert res.skipped_unverified_edition == 1
    assert res.skipped_unknown_date == 0
    assert res.scope.chunk_kinds == ["guideline"]


@pytest.mark.parametrize(("impl", "mode"), IMPLS)
def test_chunk_kinds_guideline이면_조문_판례는_안_나온다(impl, mode):
    res = _searcher(impl).search("신규성", "law", mode, 10, chunk_kinds=["guideline"])
    assert _ids(res) == ["g-new", "g-old", "g-unk"]


@pytest.mark.parametrize(("impl", "mode"), IMPLS)
def test_심사기준이_0개면_body_missing(impl, mode):
    rows = [r for r in ROWS if r.chunk_kind != "guideline"]
    res = _searcher(impl, rows).search("신규성", "law", mode, 10, chunk_kinds=["guideline"])
    assert res.status == "unverified"
    assert res.status_reason == "body_missing"


@pytest.mark.parametrize(("impl", "mode"), IMPLS)
def test_source_kinds_trial(impl, mode):
    res = _searcher(impl).search("신규성", "law", mode, 10, source_kinds=["trial"])
    assert _ids(res) == ["t-early"]


@pytest.mark.parametrize(("impl", "mode"), IMPLS)
def test_선고일이_기준일_뒤인_판례는_빠지고_날짜_모름은_센다(impl, mode):
    res = _searcher(impl).search(
        "신규성",
        "law",
        mode,
        10,
        source_kinds=["precedent", "trial"],
        decided_on_or_before=date(2021, 1, 1),
    )
    assert _ids(res) == ["p-early", "t-early"]
    assert res.skipped_unknown_date == 1
    assert res.scope.decided_on_or_before == date(2021, 1, 1)


@pytest.mark.parametrize(("impl", "mode"), IMPLS)
def test_조문은_날짜_거르기를_통과한다(impl, mode):
    res = _searcher(impl).search(
        "신규성", "law", mode, 10, chunk_kinds=["article"], decided_on_or_before=date(1990, 1, 1)
    )
    assert _ids(res) == ["a-ok", "a-unk"]
    assert res.skipped_unknown_date == 0


@pytest.mark.parametrize(("impl", "mode"), IMPLS)
def test_날짜_모름_하나만이면_0개와_not_found와_건수(impl, mode):
    res = _searcher(impl).search(
        "신규성", "law", mode, 10, doc_ids=["판례3"], decided_on_or_before=date(2021, 1, 1)
    )
    assert res.hits == []
    assert res.status == "not_found_in_scope"
    assert res.status_reason is None
    assert res.skipped_unknown_date == 1


@pytest.mark.parametrize(("impl", "mode"), IMPLS)
def test_날짜_거르기_없으면_skipped_unknown_date는_0(impl, mode):
    res = _searcher(impl).search("신규성", "law", mode, 10, doc_ids=["판례3"])
    assert res.skipped_unknown_date == 0
    assert _ids(res) == ["p-null"]


@pytest.mark.parametrize(("impl", "mode"), IMPLS)
def test_거르기_없이_부르면_전과_같다(impl, mode):
    res = _searcher(impl).search("신규성", "law", mode, 20, as_of=date(2022, 6, 1))
    # 판본 모름 둘(g-unk·a-unk)은 빠지고 센다. 새 인자는 결과 머리에 None
    assert _ids(res) == ["a-ok", "g-old", "p-early", "p-late", "p-null", "t-early"]
    assert res.skipped_unverified_edition == 2
    assert res.skipped_unknown_date == 0
    assert res.scope.chunk_kinds is None
    assert res.scope.source_kinds is None
    assert res.scope.decided_on_or_before is None


def test_SearchScope와_결과에_새_칸():
    scope = SearchScope(k=3, chunk_kinds=["guideline"], decided_on_or_before=date(2021, 1, 1))
    assert scope.model_dump(mode="json")["decided_on_or_before"] == "2021-01-01"
    with pytest.raises(ValueError):
        SearchResult(
            corpus="law",
            index_version=IV,
            mode="bm25",
            scope=scope,
            status="not_found_in_scope",
            skipped_unknown_date=-1,
        )


# ---- CheckedSearcher 입력 검사 ----


@pytest.mark.parametrize(
    "kw",
    [
        {"chunk_kinds": []},
        {"source_kinds": []},
        {"chunk_kinds": ["없는종류"]},
        {"source_kinds": ["없는유형"]},
    ],
)
def test_빈_목록과_모르는_값은_오류(kw):
    with pytest.raises(ValueError):
        _searcher("fake").search("신규성", "law", "bm25", 3, **kw)


def test_cite에_판례_인자를_주면_오류():
    cite_chunk = Chunk(
        chunk_id="cite-idx-v1:D:1",
        index_version="cite-idx-v1",
        doc_id="D",
        chunk_kind="body",
        location={"kind": "paragraph", "label": "[0001]"},
        edition=NA,
        text="신규성",
    )
    s = get_searcher(
        "fake",
        InMemoryChunkRepository({"cite": [cite_chunk]}),
        {"index_version": "cite-idx-v1"},
    )
    for kw in ({"source_kinds": ["trial"]}, {"decided_on_or_before": date(2021, 1, 1)}):
        with pytest.raises(ValueError):
            s.search("신규성", "cite", "bm25", 3, **kw)
    # chunk_kinds는 cite에도 쓸 수 있다
    assert s.search("신규성", "cite", "bm25", 3, chunk_kinds=["body"]).hits


def test_메모리_저장소는_source_kind_빈_law_조각을_statute로_채운다():
    # v1·v2 JSONL을 거치지 않고 직접 만든 조각도 Postgres(NOT NULL statute)와 같아야 한다
    old = Chunk(
        chunk_id=f"{IV}:특허법:old",
        index_version=IV,
        doc_id="특허법",
        chunk_kind="article",
        location={"kind": "article", "label": "제29조"},
        edition=_ed("2020-01-01"),
        text="신규성",
    )
    assert old.source_kind is None
    repo = InMemoryChunkRepository({"law": [old]})
    got = repo.chunks("law", IV, source_kinds=["statute"])
    assert [c.chunk_id for c in got] == [old.chunk_id]
    assert got[0].source_kind == "statute"
