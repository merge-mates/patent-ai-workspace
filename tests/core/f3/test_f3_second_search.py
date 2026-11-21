"""한 번 더 찾기 스위치(second_search, B7) 테스트. 기대값은 PRD F3 3번과 구현 계획 B7.

켜면 1차에서 근거를 못 고른 구성요소만 다른 문단·도면으로 한 번 더 찾고,
그래도 없으면 "조회 범위 내 없음" + 두 번 찾아본 범위. 끄면 1차만.
"""

import functools
import json

import pytest

from patent_ai.core.f3_claim_compare.compare import STEP, compare_unit, make_searcher
from patent_ai.core.f3_claim_compare.config import load_f3_settings
from patent_ai.core.f3_claim_compare.inputs import F3Config, F3Inputs
from patent_ai.core.f3_claim_compare.units import build_units
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.common import StatusValue
from patent_ai.core.schemas.comparison import Judgment, ParagraphSource
from patent_ai.retrieval.repository import InMemoryChunkRepository
from tests.core.f3.fakes import (
    OK,
    chunk,
    citation,
    claim_row,
    oa,
    paragraph,
    rejection,
    split,
)

D1 = "KR20990000001A"
SENSOR, TANK = "흙의 습도를 재는 습도 센서", "물을 담는 물통"
CLAIMS = {1: f"화분에 있어서, {SENSOR}; 및 {TANK}을 포함하는 화분."}
SPLITS = {1: split(1, [SENSOR, TANK])}
# "물통" 질의(벡터 [0, 1])의 순위: [0031] 1위, [0040] 2위
CHUNKS = [
    paragraph(D1, 23, "습도 센서는 흙에 꽂혀 습도를 잰다", [1.0, 0.0]),
    paragraph(D1, 31, "물통은 물을 담아 둔다", [0.0, 1.0]),
    paragraph(D1, 40, "뚜껑 아래 수조가 있다", [0.5, 0.5]),
    chunk(D1, "fig4", "도 4는 화분의 단면도", [0.2, 0.1], kind="figure", label="도 4", figures=[4]),
]
P23, P31, P40, FIG4 = (c.chunk_id for c in CHUNKS)
REPO = InMemoryChunkRepository({"cite": CHUNKS})
RESULT = oa([rejection(1, "29-2", [1], [citation("D1", D1)])])


@functools.cache
def _inner():
    return make_searcher(
        load_f3_settings(), REPO, lambda q: [1.0, 0.0] if "센서" in q else [0.0, 1.0]
    )


class _Recorder:
    def __init__(self):
        self.calls: list[dict] = []

    def search(self, query, corpus, mode, k, doc_ids=None, as_of=None):
        self.calls.append({"query": query, "k": k, "doc_ids": doc_ids})
        return _inner().search(query, corpus, mode, k, doc_ids=doc_ids, as_of=as_of)


def _answer(*rows) -> TransportResponse:
    made = [
        {
            "element_no": no,
            "citation": "D1",
            "judgment": judgment,
            "evidence": [{"chunk_id": c, "quote": q} for c, q in evidence],
        }
        for no, judgment, *evidence in rows
    ]
    return TransportResponse(json.dumps({"claim": 1, "rows": made}, ensure_ascii=False), 100, 50)


FIRST = _answer(
    (1, "disclosed", (P23, "습도 센서는 흙에 꽂혀 습도를 잰다")), (2, "difference_candidate")
)


def _run(second_search: bool, responses, *, use_examiner=True, result=None):
    result = result or RESULT
    settings = load_f3_settings()
    settings = settings.model_copy(
        update={
            "second_search": second_search,
            "second_search_depth": 2,  # 1차 k=1 다음에 상위 2까지
            "use_examiner_paragraphs": use_examiner,
            "search": settings.search.model_copy(update={"k": 1}),
        }
    )
    inputs = F3Inputs(claims_at_oa=CLAIMS, claims_status=OK, claims_document_id="d_c")
    config = F3Config(settings=settings, inputs=inputs)
    transport = FakeTransport({STEP: responses})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    searcher = _Recorder()
    units, _ = build_units(result, SPLITS)
    out = compare_unit(units[0], result, SPLITS, config, ctx=ctx, searcher=searcher, repo=REPO)
    return out, transport.calls, searcher.calls


def _tank_row(out):
    (row,) = [r for r in out.tables[0].rows if r.element == TANK]
    return row


def test_기본_설정은_켬():
    assert load_f3_settings().second_search is True


def test_끄면_한_번만_찾고_모델도_한_번만_부른다():
    out, model_calls, searches = _run(False, [FIRST])
    assert len(model_calls) == 1 and len(searches) == 2
    assert [log.round for log in out.search_log] == [1, 1]
    row = _tank_row(out)
    assert row.status.value == StatusValue.NOT_FOUND_IN_SCOPE
    assert row.status.searched_scope == "D1 조각 4개 중 hybrid 상위 1 (cite-idx-v2)"


def test_켜면_못_찾은_구성요소만_다른_문단과_도면으로_한_번_더_찾는다():
    second = _answer((2, "disclosed", (P40, "뚜껑 아래 수조가 있다")))
    out, model_calls, searches = _run(True, [FIRST, second])
    # 못 찾은 구성요소(물통)만 다시 찾는다. 1차보다 깊이(상위 2) 찾는다
    assert [(s["query"], s["k"]) for s in searches] == [(SENSOR, 1), (TANK, 1), (TANK, 2)]
    assert len(model_calls) == 2
    again = model_calls[1]["prompt"]
    assert "수조" in again and "단면도" in again  # 다음 순위 문단 + 도면 설명 조각
    assert "물통은 물을 담아 둔다" not in again  # 1차에 보여 준 조각은 뺀다
    assert "습도 센서는 흙에 꽂혀" not in again
    row = _tank_row(out)
    assert row.judgment == Judgment.DISCLOSED and row.status.value == StatusValue.CONFIRMED
    assert [e.chunk_id for e in row.evidence] == [P40]
    assert "두 번째" in row.why_retrieved
    assert [(log.round, log.element_no) for log in out.search_log] == [(1, 1), (1, 2), (2, 2)]
    assert out.search_log[2].hit_chunk_ids == [P40]  # 새로 나온 조각만


def test_두_번_찾아도_없으면_조회_범위_내_없음과_두_번_찾아본_범위를_남긴다():
    out, model_calls, _ = _run(True, [FIRST, _answer((2, "difference_candidate"))])
    assert len(model_calls) == 2
    row = _tank_row(out)
    assert row.judgment == Judgment.DIFFERENCE_CANDIDATE and row.evidence == []
    assert row.status.value == StatusValue.NOT_FOUND_IN_SCOPE
    scope = row.status.searched_scope
    assert scope == (
        "D1 조각 4개 중 hybrid 상위 1, 이어서 상위 2까지와 도면 설명 조각 1개"
        " (cite-idx-v2) · 두 번 찾음"
    )
    assert out.search_log[2].searched_scope == scope
    assert out.tables[0].status.value == StatusValue.NOT_FOUND_IN_SCOPE


def test_켜도_1차에서_다_찾았으면_다시_찾지_않는다():
    found = _answer(
        (1, "disclosed", (P23, "습도 센서는 흙에 꽂혀 습도를 잰다")),
        (2, "disclosed", (P31, "물통은 물을 담아 둔다")),
    )
    out, model_calls, searches = _run(True, [found])
    assert len(model_calls) == 1 and len(searches) == 2
    assert all(log.round == 1 for log in out.search_log)


def test_켜고_심사관_위치를_꺼도_두_번째까지_심사관_출처가_어디에도_없다():
    # 심사관이 [0040]을 짚은 통지서. 2차 검색에서 [0040]이 나와도 AI가 찾은 것으로만 남는다
    result = oa(
        [rejection(1, "29-2", [1], [citation("D1", D1)])],
        [claim_row(1, 1, ["D1"], {"D1": ["[0040]"]})],
    )
    second = _answer((2, "disclosed", (P40, "뚜껑 아래 수조가 있다")))
    out, model_calls, searches = _run(True, [FIRST, second], use_examiner=False, result=result)
    assert len(model_calls) == 2
    assert "수조" not in model_calls[0]["prompt"]  # 1차 후보에 지정 문단을 끼워 넣지 않는다
    assert all("0040" not in s["query"] for s in searches)
    assert out.examiner_locations == []
    rows = out.tables[0].rows
    assert all(r.paragraph_source == ParagraphSource.AI_FOUND for r in rows)
    assert _tank_row(out).evidence[0].chunk_id == P40 and _tank_row(out).why_retrieved


def test_두_번째_검색_깊이는_설정_값이고_1차_k보다_커야_한다():
    settings = load_f3_settings()
    assert settings.second_search_depth == 2 * settings.search.k  # 기본: 1차의 두 배
    with pytest.raises(ValueError, match="second_search_depth"):
        settings.model_validate({**settings.model_dump(), "second_search_depth": settings.search.k})
