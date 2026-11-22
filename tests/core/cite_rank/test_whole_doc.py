"""통째 LLM 검색 whole_doc_llm (이슈 #248 T1). 가짜 전송층만 쓴다: 네트워크·API 키 없음."""

import json
import logging

import pytest

from patent_ai.core.cite_rank.whole_doc import WholeDocLLMSearcher, build_variables
from patent_ai.core.llm.errors import ModelCallLimitExceeded
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.retrieval.contract import get_searcher
from patent_ai.retrieval.repository import InMemoryChunkRepository
from patent_ai.retrieval.schemas import Chunk, Edition, Location

IV = "cite-idx-v2"
STEP = "cite_rank.whole_doc"


def chunk(doc: str, start: int | None, text: str, cid: str | None = None) -> Chunk:
    label = f"[{start:04d}]" if start is not None else "표"
    return Chunk(
        chunk_id=cid or f"{doc}-{start}",
        index_version=IV,
        doc_id=doc,
        chunk_kind="body",
        location=Location(kind="paragraph", start=start, end=start, label=label),
        edition=Edition(status="not_applicable"),
        text=text,
    )


# 저장소가 주는 순서는 일부러 뒤섞는다 (정렬은 whole_doc이 한다)
CHUNKS = [
    chunk("KR2", 5, "둘째 문헌 다섯째"),
    chunk("KR1", 20, "첫 문헌 스물"),
    chunk("KR1", 10, "첫 문헌 열"),
    chunk("KR1", None, "첫 문헌 위치 없음", cid="KR1-none"),
    chunk("KR2", 1, "둘째 문헌 첫째"),
]
# 기대 순서: 문헌 -> 문단 위치(없으면 맨 뒤) -> chunk_id
EXPECTED_ORDER = ["KR1-10", "KR1-20", "KR1-none", "KR2-1", "KR2-5"]


def answer(text: str) -> TransportResponse:
    return TransportResponse(text=text, input_tokens=100, output_tokens=10, stop_reason="end_turn")


def ranked(*nums: int) -> TransportResponse:
    return answer(json.dumps({"ranked": list(nums)}))


def make(responses, chunks=CHUNKS, budget=None):
    transport = FakeTransport({STEP: responses})
    ctx = RunContext(
        run_id="r_1",
        budget=budget or CallBudget(),
        recorder=MemoryRecorder(),
        transport=transport,
    )
    repo = InMemoryChunkRepository({"cite": chunks})
    s = get_searcher_for(repo, ctx)
    return s, transport, ctx


def get_searcher_for(repo, ctx):
    return get_searcher("whole_doc_llm", repo, {"index_version": IV, "run_context": ctx})


def search(s, k=10):
    return s.search("질의", "cite", "hybrid", k)


def test_번호가_정렬된_조각에_대응하고_모델이_준_순서가_순위다():
    s, transport, _ = make([ranked(3, 1, 5)])
    r = search(s)
    # 번호 3=KR1-none, 1=KR1-10, 5=KR2-5 (정렬된 목록 기준 1부터)
    assert [h.chunk_id for h in r.hits] == ["KR1-none", "KR1-10", "KR2-5"]
    assert [h.rank for h in r.hits] == [1, 2, 3]
    assert r.status is None
    # 프롬프트에는 문헌→위치 순서로 번호가 붙은 조각이 들어간다
    prompt = transport.calls[0]["prompt"]
    assert "[1] (문헌1 [0010]) 첫 문헌 열" in prompt
    assert "[4] (문헌2 [0001]) 둘째 문헌 첫째" in prompt


def test_build_variables는_순서와_번호를_정한다():
    variables, scope = build_variables("질의", CHUNKS)
    assert [c.chunk_id for c in scope] == EXPECTED_ORDER
    lines = variables["chunks"].split("\n")
    assert lines[0] == "[1] (문헌1 [0010]) 첫 문헌 열"
    assert lines[4] == "[5] (문헌2 [0005]) 둘째 문헌 다섯째"
    assert variables["query"] == "질의"


def test_목록_밖과_중복_번호는_버리고_경고한다(caplog):
    s, _, _ = make([ranked(2, 2, 9, 0, 4)])
    with caplog.at_level(logging.WARNING):
        r = search(s)
    assert [h.chunk_id for h in r.hits] == ["KR1-20", "KR2-1"]
    # 중복 1개 + 목록 밖 2개 = 3개 버림
    assert any("3" in m and "버" in m for m in caplog.messages)


def test_k보다_많이_내면_k개로_자른다():
    s, _, _ = make([ranked(1, 2, 3, 4, 5)])
    r = search(s, k=2)
    assert [h.chunk_id for h in r.hits] == ["KR1-10", "KR1-20"]


def test_빈_범위는_body_missing이고_모델을_부르지_않는다():
    # 색인 판은 있지만 이 문헌에는 조각이 없다
    s, transport, _ = make([ranked(1)])
    r = s.search("질의", "cite", "hybrid", 10, doc_ids=["KR9"])
    assert (r.status, r.status_reason, r.hits) == ("unverified", "body_missing", [])
    assert transport.calls == []


def test_출력_검사가_한번_실패하면_한번_더_부른다():
    s, transport, ctx = make([answer("JSON 아님"), ranked(1)])
    r = search(s)
    assert [h.chunk_id for h in r.hits] == ["KR1-10"]
    assert len(transport.calls) == 2
    # 호출 기록(recorder)에 두 번 다 남는다 (채점기가 비용을 합친다)
    assert len(ctx.recorder.records) == 2


def test_출력_검사_두번_실패하면_unverified_not_extracted():
    s, transport, _ = make([answer("틀림"), answer('{"ranked": "x"}')])
    r = search(s)
    assert (r.status, r.status_reason, r.hits) == ("unverified", "not_extracted", [])
    assert len(transport.calls) == 2


def test_고른_번호가_모두_목록_밖이면_조용히_넘기지_않고_unverified():
    s, _, _ = make([ranked(99)])
    r = search(s)
    assert r.status == "unverified"
    assert r.status_reason == "not_extracted"


def test_호출_상한에_닿으면_예외가_그대로_올라온다():
    budget = CallBudget()
    budget.add("r_1", STEP, 0)  # 이미 한 번 쓴 것으로 센다
    # 설정의 max_model_calls 대신 아주 작은 상한을 settings로 줄 수 없으니 상한을 채워서 확인
    for _ in range(150):
        budget.add("r_1", STEP, 0)
    s, _, _ = make([ranked(1)], budget=budget)
    with pytest.raises(ModelCallLimitExceeded):
        search(s)


def test_run_context가_없으면_분명한_오류로_멈춘다():
    repo = InMemoryChunkRepository({"cite": CHUNKS})
    with pytest.raises(ValueError, match="run_context"):
        WholeDocLLMSearcher(repo, {"index_version": IV})


def test_모델이_빈_순위를_내면_not_found_in_scope():
    # 관련 조각이 없다고 답한 것은 출력 실패가 아니라 "조회 범위 내 없음"
    s, _, _ = make([ranked()])
    r = search(s)
    assert (r.status, r.status_reason, r.hits) == ("not_found_in_scope", None, [])
