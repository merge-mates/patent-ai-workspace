"""고정 루프(B) 테스트. 기대값은 구현 계획 m3-i2-309b task-3: 질의 3개 -> 검색 3번·기록 3줄,
1차에 보여 준 조각은 뺌, 새 조각 0개면 경고, 다시 쓰기 실패는 예외로 올린다."""

import json
import logging

import pytest

from patent_ai.core.f3_claim_compare.citations import ResolvedCitation
from patent_ai.core.f3_claim_compare.compare import make_searcher
from patent_ai.core.f3_claim_compare.config import load_f3_settings
from patent_ai.core.f3_claim_compare.recheck.config import load_recheck_settings
from patent_ai.core.f3_claim_compare.recheck.fixed_loop import (
    fixed_loop_candidates,
    rewrite_queries,
)
from patent_ai.core.llm.errors import ModelCallFailed, ModelCallLimitExceeded, ModelOutputInvalid
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.common import StatusValue
from patent_ai.retrieval.repository import InMemoryChunkRepository
from tests.core.f3.fakes import paragraph, split

STEP = "recheck.rewrite"
D1 = "KR20990000001A"
CHUNKS = [
    paragraph(D1, 1, "습도 센서는 흙에 꽂힌다", [1.0, 0.0]),
    paragraph(D1, 2, "물통은 물을 담아 둔다", [0.0, 1.0]),
    paragraph(D1, 3, "뚜껑 아래 수조가 있다", [0.5, 0.5]),
]
P1, P2, P3 = (c.chunk_id for c in CHUNKS)
REPO = InMemoryChunkRepository({"cite": CHUNKS})
SEARCHER = make_searcher(load_f3_settings(), REPO, lambda q: [0.0, 1.0])
CITE = ResolvedCitation.model_construct(label="D1", doc_id=D1, chunk_count=3, compared=None)
ELEMENT = split(1, ["물을 담는 물통"]).elements[0]
CLAIM_TEXT = "화분에 있어서, 물을 담는 물통을 포함하는 화분."


def _reply(queries) -> TransportResponse:
    return TransportResponse(json.dumps({"queries": queries}, ensure_ascii=False), 100, 50)


def _ctx(*responses):
    transport = FakeTransport({STEP: list(responses)})
    budget, recorder = CallBudget(), MemoryRecorder()
    ctx = RunContext(run_id="r", budget=budget, recorder=recorder, transport=transport)
    return ctx, transport


def _recheck(rewrite_k=10, rewrite_n=3):
    base = load_recheck_settings()
    search = base.search.model_copy(update={"rewrite_k": rewrite_k, "rewrite_n": rewrite_n})
    return base.model_copy(update={"search": search})


class _Recorder:
    def __init__(self):
        self.calls = []

    def search(self, query, corpus, mode, k, doc_ids=None, **kw):
        self.calls.append({"query": query, "k": k, "doc_ids": doc_ids, "mode": mode})
        return SEARCHER.search(query, corpus, mode, k, doc_ids=doc_ids, **kw)


def _run(ctx, shown, recheck=None, searcher=None):
    log: list = []
    found = fixed_loop_candidates(
        unit_id="u1",
        claim=1,
        item_n=1,
        element=ELEMENT,
        claim_text=CLAIM_TEXT,
        cite=CITE,
        shown=shown,
        settings=load_f3_settings(),
        recheck=recheck or _recheck(),
        ctx=ctx,
        searcher=searcher or SEARCHER,
        search_log=log,
    )
    return found, log


def test_다시_쓰기는_질의_목록을_돌려주고_프롬프트에_구성요소와_개수가_들어간다():
    ctx, transport = _ctx(_reply(["수조", "저장 용기", "급수"]))
    assert rewrite_queries(ELEMENT.text, CLAIM_TEXT, ctx, n=3) == ["수조", "저장 용기", "급수"]
    prompt = transport.calls[0]["prompt"]
    assert ELEMENT.text in prompt and CLAIM_TEXT in prompt and "3개" in prompt


def test_다시_쓰기가_n보다_많이_주면_앞_n개만_쓰고_빈_질의와_중복은_뺀다():
    ctx, _ = _ctx(_reply(["수조", "수조", " ", "용기", "급수"]))
    assert rewrite_queries(ELEMENT.text, CLAIM_TEXT, ctx, n=2) == ["수조", "용기"]


def test_다시_쓰기_전송이_실패하면_ModelCallFailed가_올라온다():
    ctx, _ = _ctx(ModelCallFailed("전송 오류"))
    with pytest.raises(ModelCallFailed):
        rewrite_queries(ELEMENT.text, CLAIM_TEXT, ctx, n=3)


def test_호출_상한에_닿으면_ModelCallLimitExceeded가_올라온다():
    ctx, transport = _ctx(_reply(["수조"]))
    for _ in range(200):  # config/recheck.yaml rewrite.max_model_calls 만큼 이미 씀
        ctx.budget.add(ctx.run_id, STEP, 1)
    with pytest.raises(ModelCallLimitExceeded):
        rewrite_queries(ELEMENT.text, CLAIM_TEXT, ctx, n=3)
    assert transport.calls == []


def test_다시_쓰기_답이_형식에_안_맞으면_ModelOutputInvalid가_올라온다():
    bad = TransportResponse(json.dumps({"queries": []}), 1, 1)
    ctx, _ = _ctx(bad, bad, bad)
    with pytest.raises(ModelOutputInvalid):
        rewrite_queries(ELEMENT.text, CLAIM_TEXT, ctx, n=3)


def test_질의_3개면_검색_3번과_검색_기록_3줄이고_1차에_보여_준_조각은_뺀다():
    ctx, _ = _ctx(_reply(["수조", "저장 용기", "급수"]))
    searcher = _Recorder()
    found, log = _run(ctx, shown={P2}, searcher=searcher)
    assert [(c["query"], c["k"], c["doc_ids"], c["mode"]) for c in searcher.calls] == [
        (q, 10, [D1], "hybrid") for q in ("수조", "저장 용기", "급수")
    ]
    assert P2 not in found and set(found) == {P1, P3}
    assert all(c.label == "D1" for c in found.values())
    assert len(log) == 3
    for row in log:
        assert row.round == 2 and row.citation == "D1" and row.doc_id == D1
        assert (row.unit_id, row.claim, row.element_claim, row.element_no) == ("u1", 1, 1, 1)
        assert "다시 찾기(fixed_loop): 질의 3개" in row.searched_scope
        assert row.status.value == StatusValue.CONFIRMED
        assert P2 not in row.hit_chunk_ids


def test_rewrite_k를_검색_깊이로_쓴다():
    ctx, _ = _ctx(_reply(["수조"]))
    searcher = _Recorder()
    _run(ctx, shown=set(), recheck=_recheck(rewrite_k=2, rewrite_n=1), searcher=searcher)
    assert [c["k"] for c in searcher.calls] == [2]


def test_새_조각이_0개면_경고하고_기록은_조회_범위_내_없음(caplog):
    ctx, _ = _ctx(_reply(["수조", "용기"]))
    with caplog.at_level(logging.WARNING):
        found, log = _run(ctx, shown={P1, P2, P3})
    assert found == {}
    assert any("새 조각이 0개" in r.getMessage() for r in caplog.records)
    assert [r.status.value for r in log] == [StatusValue.NOT_FOUND_IN_SCOPE] * 2
    assert all(r.status.searched_scope for r in log)


def test_다시_쓰기가_실패하면_검색하지_않고_예외를_올린다():
    ctx, _ = _ctx(ModelCallFailed("전송 오류"))
    searcher = _Recorder()
    with pytest.raises(ModelCallFailed):
        _run(ctx, shown=set(), searcher=searcher)
    assert searcher.calls == []


def test_다시_쓴_질의가_빈_글뿐이면_ModelOutputInvalid이고_검색은_안_돈다():
    ctx, _ = _ctx(_reply([" ", ""]))
    recorder = _Recorder()
    with pytest.raises(ModelOutputInvalid):
        _run(ctx, set(), searcher=recorder)
    assert recorder.calls == []


def test_본문_없는_인용문헌이면_assert가_아니라_ValueError():
    ctx, _ = _ctx(_reply(["수조"]))
    nobody = ResolvedCitation.model_construct(label="D1", doc_id=None, chunk_count=0, compared=None)
    with pytest.raises(ValueError):
        fixed_loop_candidates(
            unit_id="u1",
            claim=1,
            item_n=1,
            element=ELEMENT,
            claim_text=CLAIM_TEXT,
            cite=nobody,
            shown=set(),
            settings=load_f3_settings(),
            recheck=_recheck(),
            ctx=ctx,
            searcher=SEARCHER,
            search_log=[],
        )
