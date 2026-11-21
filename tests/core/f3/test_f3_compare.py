"""대비 단계(B2) 테스트: 지어낸 청구항·조각 + 기록된 모델 응답 + 메모리 조각 저장소. 진짜 호출 없음.

기대값은 구현 계획(B2)과 F3 뼈대 설계 3·5·6·7절에서 가져왔다. 프롬프트 문구는 테스트하지 않는다.
"""

import functools
import json
import logging

import pytest

from patent_ai.core.f3_claim_compare.compare import (
    STEP,
    compare_unit,
    compare_units,
    make_searcher,
    memo_embed,
)
from patent_ai.core.f3_claim_compare.config import load_f3_settings
from patent_ai.core.f3_claim_compare.inputs import F3Config, F3Inputs
from patent_ai.core.f3_claim_compare.units import build_units
from patent_ai.core.llm.config import load_step_config
from patent_ai.core.llm.embed import load_embed_config
from patent_ai.core.llm.errors import ModelConfigError
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.common import Flag, StatusValue, UnverifiedReason
from patent_ai.core.schemas.comparison import Judgment, NoveltyVerdict, ParagraphSource
from patent_ai.retrieval.repository import InMemoryChunkRepository
from tests.core.f3.fakes import IV, OK, bad, citation, claim_row, oa, paragraph, rejection, split

D1, D2 = "KR20990000001A", "KR20990000002A"
SENSOR, TANK = "흙의 습도를 재는 습도 센서", "물을 담는 물통"
CLAIMS = {1: f"화분에 있어서, {SENSOR}; 및 {TANK}을 포함하는 화분."}
SPLITS = {1: split(1, [SENSOR, TANK])}

# 질의 벡터: "센서"가 있으면 [1, 0], 아니면 [0, 1] (아래 _embed)
CHUNKS = [
    paragraph(D1, 23, "습도 센서는 흙에 꽂혀 습도를 잰다", [1.0, 0.0]),
    paragraph(D1, 31, "물통은 물을 담아 둔다", [0.0, 1.0]),
    paragraph(D1, 40, "뚜껑 아래 수조가 있다", [0.5, 0.5]),  # 검색 1위는 아니고 심사관이 짚은 문단
    paragraph(D2, 10, "제어부는 밸브를 연다", [0.5, 0.5]),
]
P23, P31, P40, P10 = (c.chunk_id for c in CHUNKS)
REPO = InMemoryChunkRepository({"cite": CHUNKS})


class _Recorder:
    """검색기를 감싸 받은 질의와 범위를 적어 둔다."""

    def __init__(self, inner):
        self.inner = inner
        self.calls: list[dict] = []

    def search(self, query, corpus, mode, k, doc_ids=None, as_of=None):
        self.calls.append({"query": query, "mode": mode, "k": k, "doc_ids": doc_ids})
        return self.inner.search(query, corpus, mode, k, doc_ids=doc_ids, as_of=as_of)


def _embed(query: str) -> list[float]:
    return [1.0, 0.0] if "센서" in query else [0.0, 1.0]


def _config(*, use_examiner=True, k=1, claims_status=OK) -> F3Config:
    settings = load_f3_settings()
    settings = settings.model_copy(
        update={
            "use_examiner_paragraphs": use_examiner,
            # 가짜 응답 개수는 한 번만 찾기 기준 (한 번 더 찾기는 test_f3_second_search.py가 본다)
            "second_search": False,
            "search": settings.search.model_copy(update={"k": k}),
        }
    )
    inputs = F3Inputs(claims_at_oa=CLAIMS, claims_status=claims_status, claims_document_id="d_c")
    return F3Config(settings=settings, inputs=inputs)


@functools.cache
def _inner_searcher():
    # 형태소 분석기를 테스트마다 다시 띄우지 않게 한 번만 만든다 (k는 검색할 때 넘긴다)
    return make_searcher(load_f3_settings(), REPO, _embed)


def _row(element_no: int, label: str, judgment: str, *evidence: tuple[str, str]) -> dict:
    picks = [{"chunk_id": chunk_id, "quote": quote} for chunk_id, quote in evidence]
    return {"element_no": element_no, "citation": label, "judgment": judgment, "evidence": picks}


def _answer(rows: list[dict], claim: int = 1) -> TransportResponse:
    return TransportResponse(
        json.dumps({"claim": claim, "rows": rows}, ensure_ascii=False), 100, 50
    )


def _run(result, responses, config=None, splits=None):
    """첫 판단 단위를 대비한다. (결과, 모델 호출 기록, 검색 호출 기록)을 돌려준다."""
    config = config or _config()
    splits = splits or SPLITS
    transport = FakeTransport({STEP: responses})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    searcher = _Recorder(_inner_searcher())
    units, _ = build_units(result, splits)
    out = compare_unit(units[0], result, splits, config, ctx=ctx, searcher=searcher, repo=REPO)
    return out, transport.calls, searcher.calls


def _inventive(citations=None, rows=()):
    citations = citations or [citation("D1", D1)]
    return oa([rejection(1, "29-2", [1], citations, reasoning="D1에 D2를 결합")], rows)


def _find(table, element_no: int, label: str, source=None):
    location = f"청구항 1 [구성 1-{element_no}]"
    found = [
        r
        for r in table.rows
        if r.element_location == location
        and r.citation == label
        and (source is None or r.paragraph_source == source)
    ]
    assert len(found) == 1, found
    return found[0]


# 심사관이 청구항 1에 D1 [0040]을 짚은 통지서
EXAMINER_OA = _inventive(rows=[claim_row(1, 1, ["D1"], {"D1": ["[0040]"]})])
BOTH = _answer(
    [
        _row(1, "D1", "disclosed", (P23, "습도 센서는 흙에 꽂혀 습도를 잰다")),
        _row(2, "D1", "disclosed", (P40, "뚜껑 아래 수조가 있다")),
    ]
)


# ---- 심사관 지정 / AI 찾음 ----
def test_심사관_지정_문단과_AI가_찾은_문단을_나눈다():
    out, model_calls, searches = _run(EXAMINER_OA, BOTH)
    (table,) = out.tables
    assert table.unit_id == "oa_1:29-2:c1"
    ai = _find(table, 1, "D1")
    assert ai.paragraph_source == ParagraphSource.AI_FOUND and ai.why_retrieved
    assert ai.judgment == Judgment.DISCLOSED and ai.status.value == StatusValue.CONFIRMED
    assert (ai.claim, ai.element) == (1, SENSOR)
    (evidence,) = ai.evidence
    assert (evidence.document_id, evidence.chunk_id, evidence.index_version) == (D1, P23, IV)
    assert (evidence.location, evidence.raw_text) == ("[0023]", "습도 센서는 흙에 꽂혀 습도를 잰다")
    examiner = _find(table, 2, "D1")
    assert examiner.paragraph_source == ParagraphSource.EXAMINER
    assert examiner.why_retrieved is None
    assert examiner.evidence[0].chunk_id == P40 and examiner.evidence[0].location == "[0040]"
    # 심사관 조각은 표시 없이 후보에 들어가고, 검색 질의는 구성요소 원문뿐이다
    assert len(model_calls) == 1 and "수조" in model_calls[0]["prompt"]
    assert [s["query"] for s in searches] == [SENSOR, TANK]
    assert all(s["doc_ids"] == [D1] and s["mode"] == "hybrid" and s["k"] == 1 for s in searches)
    (located,) = out.examiner_locations
    assert (located.claim, located.citation, located.location) == (1, "D1", "[0040]")
    assert located.chunk_ids == [P40] and located.status.value == StatusValue.CONFIRMED


def test_심사관_위치를_끄면_어디에도_들어가지_않고_모든_줄이_AI_찾음():
    out, model_calls, searches = _run(EXAMINER_OA, [BOTH, BOTH], _config(use_examiner=False))
    (table,) = out.tables
    assert all(r.paragraph_source == ParagraphSource.AI_FOUND for r in table.rows)
    assert out.examiner_locations == []
    # 지정 문단의 글자가 어느 프롬프트에도 없고, 번호는 첫 프롬프트에 없다
    # (두 번째 프롬프트의 검사 오류에는 모델이 스스로 적어 낸 chunk_id가 되돌아간다)
    assert all("수조" not in call["prompt"] for call in model_calls)
    assert "0040" not in model_calls[0]["prompt"]
    assert all("0040" not in s["query"] for s in searches)
    # 후보에 없는 조각을 근거로 준 줄은 근거를 버린다
    dropped = _find(table, 2, "D1")
    assert dropped.evidence == [] and dropped.judgment == Judgment.UNCLEAR
    assert dropped.status.reason == UnverifiedReason.EVIDENCE_REJECTED


def test_못_맞춘_심사관_위치는_근거_없이_확인되지_않음으로_남긴다():
    result = _inventive(rows=[claim_row(1, 1, ["D1"], {"D1": ["[0099]", "제어부(130)"]})])
    answer = _answer([_row(1, "D1", "unclear"), _row(2, "D1", "unclear")])
    out, _, _ = _run(result, answer)
    reasons = {x.location: x.status.reason for x in out.examiner_locations}
    assert reasons == {
        "[0099]": UnverifiedReason.EVIDENCE_REJECTED,
        "제어부(130)": UnverifiedReason.AMBIGUOUS,
    }
    assert all(x.chunk_ids == [] for x in out.examiner_locations)


# ---- 못 찾음 ----
def test_근거를_못_고르면_조회_범위_내_없음과_찾아본_범위를_남긴다():
    answer = _answer(
        [
            _row(1, "D1", "disclosed", (P23, "습도 센서는 흙에 꽂혀 습도를 잰다")),
            _row(2, "D1", "difference_candidate"),
        ]
    )
    out, _, _ = _run(_inventive(), answer)
    (table,) = out.tables
    missing = _find(table, 2, "D1")
    assert missing.judgment == Judgment.DIFFERENCE_CANDIDATE
    assert missing.paragraph_source == ParagraphSource.AI_FOUND and missing.why_retrieved
    assert missing.status.value == StatusValue.NOT_FOUND_IN_SCOPE
    assert missing.status.searched_scope == "D1 조각 3개 중 hybrid 상위 1 (cite-idx-v2)"
    assert missing.evidence == []
    # 결과 status = 줄 중 가장 나쁜 값
    assert table.status.value == StatusValue.NOT_FOUND_IN_SCOPE


def test_근거_없이_개시됨이라고_하면_불명으로_낮춘다():
    answer = _answer([_row(1, "D1", "disclosed"), _row(2, "D1", "difference_candidate")])
    out, calls, _ = _run(_inventive(), [answer, answer])
    row = _find(out.tables[0], 1, "D1")
    assert len(calls) == 2  # 검사 오류라 한 번 다시 부른다
    assert row.judgment == Judgment.UNCLEAR
    assert row.status.reason == UnverifiedReason.EVIDENCE_REJECTED
    assert out.tables[0].status.value == StatusValue.UNVERIFIED  # 가장 나쁜 값


# ---- 근거 대조 ----
def test_조각에_없는_글자를_근거로_주면_한_번_다시_부르고_그래도_틀리면_버린다(caplog):
    wrong = _answer(
        [_row(1, "D1", "disclosed", (P23, "센서는 온도를 잰다")), _row(2, "D1", "unclear")]
    )
    with caplog.at_level(logging.WARNING):
        out, calls, _ = _run(_inventive(), [wrong, wrong])
    assert len(calls) == 2 and "검사 오류" in calls[1]["prompt"]
    row = _find(out.tables[0], 1, "D1")
    assert row.evidence == [] and row.judgment == Judgment.UNCLEAR
    assert row.status.reason == UnverifiedReason.EVIDENCE_REJECTED
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_다시_불러_고쳐_오면_통과한다():
    wrong = _answer(
        [_row(1, "D1", "disclosed", (P23, "센서는 온도를 잰다")), _row(2, "D1", "unclear")]
    )
    good = _answer(
        [
            _row(1, "D1", "disclosed", (P23, "습도 센서는 흙에 꽂혀 습도를 잰다")),
            _row(2, "D1", "unclear"),
        ]
    )
    out, calls, _ = _run(_inventive(), [wrong, good])
    assert len(calls) == 2
    assert _find(out.tables[0], 1, "D1").status.value == StatusValue.CONFIRMED


def test_근거_일부만_틀리면_맞는_근거는_남기고_상태를_낮춘다():
    mixed = _answer(
        [
            _row(
                1,
                "D1",
                "disclosed",
                (P23, "습도 센서는 흙에 꽂혀 습도를 잰다"),
                ("없는:조각", "글자"),
            ),
            _row(2, "D1", "unclear"),
        ]
    )
    out, _, _ = _run(_inventive(), [mixed, mixed])
    row = _find(out.tables[0], 1, "D1")
    assert [e.chunk_id for e in row.evidence] == [P23]
    assert row.judgment == Judgment.DISCLOSED
    assert row.status.reason == UnverifiedReason.EVIDENCE_REJECTED


def test_모델이_판정을_빼먹은_줄은_버리지_않고_확인되지_않음():
    partial = _answer([_row(1, "D1", "disclosed", (P23, "습도 센서는 흙에 꽂혀 습도를 잰다"))])
    out, calls, _ = _run(_inventive(), [partial, partial])
    assert len(calls) == 2
    row = _find(out.tables[0], 2, "D1")
    assert row.judgment == Judgment.UNCLEAR
    assert row.status.reason == UnverifiedReason.NOT_EXTRACTED


def test_두_번_다_형식이_틀리면_그_단위만_보류하고_이유를_남긴다():
    broken = TransportResponse("대비 결과입니다", 100, 50)
    out, _, _ = _run(_inventive(), [broken, broken])
    assert out.tables == []
    assert [h.task for h in out.held_tasks] == ["f3_compare:oa_1:29-2:c1:call_failed"]
    assert [type(e).__name__ for e in out.call_errors] == ["ModelOutputInvalid"]


# ---- 인용문헌 ----
def test_대비하지_않는_인용문헌은_표에_이유와_함께_남고_줄은_만들지_않는다():
    cited = [
        citation("D1", D1),
        citation("D2", "JP2099000001A", country="JP"),
        citation("D3", "KR20990000009A"),  # 색인에 조각 없음
        citation("D4", None),
    ]
    answer = _answer([_row(1, "D1", "unclear"), _row(2, "D1", "unclear")])
    out, _, searches = _run(_inventive(cited), answer)
    (table,) = out.tables
    by_label = {c.label: c for c in table.citations}
    assert [c.compared for c in table.citations] == [True, False, False, False]
    assert by_label["D2"].skipped_status.reason == UnverifiedReason.LOOKUP_FAILED
    assert by_label["D3"].skipped_status.reason == UnverifiedReason.BODY_MISSING
    assert by_label["D4"].skipped_status.reason == UnverifiedReason.AMBIGUOUS
    assert Flag.NEEDS_HUMAN_REVIEW in table.flags
    assert {r.citation for r in table.rows} == {"D1"}
    assert all(s["doc_ids"] == [D1] for s in searches)
    # 이 입력에는 최초 명세서가 없어 효과 후보를 못 뽑는 보류가 같이 남는다 (이슈 #30 C2)
    assert [h.task for h in out.held_tasks] == [
        "f3_compare:oa_1:D3",
        "f3_compare:oa_1:spec",
        "f3_compare:oa_1:29-2:c1:spec",
    ]


def test_결합_진보성은_인용문헌마다_따로_찾고_줄도_따로다():
    cited = [citation("D1", D1), citation("D2", D2)]
    answer = _answer(
        [
            _row(1, "D1", "disclosed", (P23, "습도 센서는 흙에 꽂혀 습도를 잰다")),
            _row(2, "D1", "disclosed", (P31, "물통은 물을 담아 둔다")),
            _row(1, "D2", "difference_candidate"),
            _row(2, "D2", "difference_candidate"),
        ]
    )
    out, _, searches = _run(_inventive(cited), answer)
    (table,) = out.tables
    assert [(s["query"], s["doc_ids"]) for s in searches] == [
        (SENSOR, [D1]),
        (SENSOR, [D2]),
        (TANK, [D1]),
        (TANK, [D2]),
    ]
    assert len(table.rows) == 4
    assert (
        _find(table, 1, "D2").status.searched_scope == "D2 조각 1개 중 hybrid 상위 1 (cite-idx-v2)"
    )


# ---- 진보성 요약 ----
def test_진보성_요약은_어느_문헌에도_개시되지_않은_구성요소와_심사관_결합_논리를_모은다(caplog):
    cited = [citation("D1", D1), citation("D2", D2)]
    answer = _answer(
        [
            _row(1, "D1", "disclosed", (P23, "습도 센서는 흙에 꽂혀 습도를 잰다")),
            _row(2, "D1", "difference_candidate"),
            _row(1, "D2", "difference_candidate"),
            _row(2, "D2", "unclear"),
        ]
    )
    with caplog.at_level(logging.WARNING):
        out, _, _ = _run(_inventive(cited), answer)
    summary = out.tables[0].summary
    assert summary.kind == "inventive_step"
    # 근거 없는 차이 후보는 "조회 범위 내 없음"과 찾아본 범위를 붙인다 (없다는 판단이 아님)
    assert summary.differences == [
        f"청구항 1 [구성 1-2] {TANK} "
        "(조회 범위 내 없음: D1 조각 3개 중 hybrid 상위 1 (cite-idx-v2), 없다는 판단 아님)"
    ]
    assert summary.combination == "D1에 D2를 결합"  # 심사관 논리 값 그대로
    assert summary.effect_candidates == []
    assert Flag.NEEDS_HUMAN_REVIEW in out.tables[0].flags
    assert any("효과 후보" in r.getMessage() for r in caplog.records)


def test_두_문헌_모두_근거_없는_차이_후보면_찾아본_범위를_세미콜론으로_이어_붙인다():
    cited = [citation("D1", D1), citation("D2", D2)]
    answer = _answer(
        [
            _row(1, "D1", "difference_candidate"),
            _row(1, "D2", "difference_candidate"),
            _row(2, "D1", "disclosed", (P31, "물통은 물을 담아 둔다")),
            _row(2, "D2", "unclear"),
        ]
    )
    out, _, _ = _run(_inventive(cited), answer)
    d1_scope = "D1 조각 3개 중 hybrid 상위 1 (cite-idx-v2)"
    d2_scope = "D2 조각 1개 중 hybrid 상위 1 (cite-idx-v2)"
    assert out.tables[0].summary.differences == [
        f"청구항 1 [구성 1-1] {SENSOR} "
        f"(조회 범위 내 없음: {d1_scope}; {d2_scope}, 없다는 판단 아님)"
    ]


# ---- 신규성 ----
def _novelty(citations):
    return oa([rejection(1, "29-1-1", [1], citations)])


def test_신규성_대비표는_인용문헌_하나와만_대비한다():
    d1 = _answer(
        [
            _row(1, "D1", "disclosed", (P23, "습도 센서는 흙에 꽂혀 습도를 잰다")),
            _row(2, "D1", "disclosed", (P31, "물통은 물을 담아 둔다")),
        ]
    )
    d2 = _answer([_row(1, "D2", "difference_candidate"), _row(2, "D2", "unclear")])
    out, calls, _ = _run(_novelty([citation("D1", D1), citation("D2", D2)]), [d1, d2])
    first, second = out.tables  # 인용문헌마다 표 하나
    assert first.unit_id == second.unit_id == "oa_1:29-1-1:c1"
    for table, label in ((first, "D1"), (second, "D2")):
        assert [c.label for c in table.citations if c.compared] == [label]
        assert {r.citation for r in table.rows} == {label}  # 두 문헌을 합친 줄이 없다
        assert table.summary.kind == "novelty" and table.summary.citation == label
        assert "판정 아님" in table.summary.reason
    assert first.summary.verdict == NoveltyVerdict.NO_DIFFERENCE
    assert second.summary.verdict == NoveltyVerdict.DIFFERENT
    # 모델도 문헌마다 따로 부르고, 다른 문헌의 조각을 같이 보여 주지 않는다
    assert len(calls) == 2
    assert "밸브" not in calls[0]["prompt"] and "습도 센서는 흙에" not in calls[1]["prompt"]


def test_신규성_불명만_있으면_실질적_동일_후보로_모은다():
    answer = _answer(
        [
            _row(1, "D1", "disclosed", (P23, "습도 센서는 흙에 꽂혀 습도를 잰다")),
            _row(2, "D1", "unclear"),
        ]
    )
    out, _, _ = _run(_novelty([citation("D1", D1)]), answer)
    assert out.tables[0].summary.verdict == NoveltyVerdict.SUBSTANTIALLY_SAME_CANDIDATE


def test_쓸_인용문헌이_없으면_표를_만들지_않고_보류한다(caplog):
    with caplog.at_level(logging.WARNING):
        out, calls, searches = _run(_novelty([citation("D1", "JP1A", country="JP")]), [])
    assert out.tables == [] and calls == [] and searches == []
    assert [h.task for h in out.held_tasks] == ["f3_compare:oa_1:29-1-1:c1"]
    assert any(r.levelno == logging.WARNING for r in caplog.records)


# ---- 입력 상태 전파 ----
def test_청구항_판이_확인되지_않으면_줄이_모두_input_unverified():
    config = _config(claims_status=bad(UnverifiedReason.EDITION_UNKNOWN))
    answer = _answer(
        [
            _row(1, "D1", "disclosed", (P23, "습도 센서는 흙에 꽂혀 습도를 잰다")),
            _row(2, "D1", "difference_candidate"),
        ]
    )
    out, _, _ = _run(_inventive(), answer, config)
    (table,) = out.tables
    assert all(r.status.reason == UnverifiedReason.INPUT_UNVERIFIED for r in table.rows)
    assert table.status.value == StatusValue.UNVERIFIED


def test_원문에서_확인하지_못한_구성요소는_찾지_않고_확인되지_않음_줄로_남긴다():
    base = split(1, [SENSOR, TANK])
    lost = base.elements[1].model_copy(update={"start": None, "end": None, "status": bad()})
    splits = {1: base.model_copy(update={"elements": [base.elements[0], lost]})}
    answer = _answer([_row(1, "D1", "disclosed", (P23, "습도 센서는 흙에 꽂혀 습도를 잰다"))])
    out, calls, searches = _run(_inventive(), answer, splits=splits)
    assert [s["query"] for s in searches] == [SENSOR] and len(calls) == 1
    row = _find(out.tables[0], 2, "D1")
    assert row.judgment == Judgment.UNCLEAR
    assert row.status.reason == UnverifiedReason.INPUT_UNVERIFIED


# ---- 검색 기록 ----
def test_검색_기록에는_구성요소_원문_대신_해시와_걸린_조각이_남는다():
    answer = _answer([_row(1, "D1", "unclear"), _row(2, "D1", "unclear")])
    out, _, _ = _run(_inventive(), answer)
    first, second = out.search_log
    assert (first.unit_id, first.claim, first.element_no) == ("oa_1:29-2:c1", 1, 1)
    assert (first.citation, first.doc_id, first.round) == ("D1", D1, 1)
    assert first.hit_chunk_ids == [P23] and second.hit_chunk_ids == [P31]
    assert first.searched_scope == "D1 조각 3개 중 hybrid 상위 1 (cite-idx-v2)"
    assert SENSOR not in first.model_dump_json() and len(first.element_hash) == 12


# ---- 여러 단위 ----
def test_명확성_단위는_건너뛰고_대비표만_모은다():
    result = oa([rejection(1, "29-2", [1], [citation("D1", D1)]), rejection(2, "42-4-2", [1])])
    units, _ = build_units(result, SPLITS)
    answer = _answer([_row(1, "D1", "unclear"), _row(2, "D1", "unclear")])
    transport = FakeTransport({STEP: [answer]})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    config = _config()
    searcher = _inner_searcher()
    out = compare_units(units, result, SPLITS, config, ctx=ctx, searcher=searcher, repo=REPO)
    assert [t.unit_id for t in out.tables] == ["oa_1:29-2:c1"]


# ---- 설정·임베딩 ----
def test_compare와_embed_단계_설정():
    cfg = load_step_config("f3.compare")
    assert (cfg.model, cfg.effort, cfg.max_tokens) == ("claude-haiku-5-5", "medium", 64000)
    assert cfg.prompt == "prompts/f3/compare.md" and cfg.max_model_calls is not None
    embed = load_embed_config("f3.embed")
    assert embed.model == load_embed_config("cite_search.embed").model
    assert embed.max_model_calls is not None


def test_같은_질의는_임베딩을_한_번만_부른다():
    seen: list[str] = []

    def embed(text: str) -> list[float]:
        seen.append(text)
        return [1.0, 0.0]

    memo = memo_embed(embed)
    assert memo("물통") == memo("물통") == [1.0, 0.0]
    memo("센서")
    assert seen == ["물통", "센서"]


# ---- B2 리뷰 고침 ----
FULL23 = "습도 센서는 흙에 꽂혀 습도를 잰다"
ONE_DIFFERENT = _answer(
    [_row(1, "D1", "disclosed", (P23, FULL23)), _row(2, "D1", "difference_candidate")]
)


def test_청구항_판이_확인되지_않아도_요약에서_차이_후보가_빠지지_않는다():
    config = _config(claims_status=bad(UnverifiedReason.EDITION_UNKNOWN))
    novelty, _, _ = _run(_novelty([citation("D1", D1)]), ONE_DIFFERENT, config)
    assert novelty.tables[0].summary.verdict == NoveltyVerdict.DIFFERENT
    inventive, _, _ = _run(_inventive(), ONE_DIFFERENT, config)
    assert inventive.tables[0].summary.differences == [
        f"청구항 1 [구성 1-2] {TANK} "
        "(조회 범위 내 없음: D1 조각 3개 중 hybrid 상위 1 (cite-idx-v2), 없다는 판단 아님)"
    ]


def _splits_with_lost_element():
    base = split(1, [SENSOR, TANK])
    lost = base.elements[1].model_copy(update={"start": None, "end": None, "status": bad()})
    return {1: base.model_copy(update={"elements": [base.elements[0], lost]})}


def test_확인_못_한_구성요소가_있으면_차이_없음으로_모으지_않는다():
    answer = _answer([_row(1, "D1", "disclosed", (P23, FULL23))])
    out, _, _ = _run(_novelty([citation("D1", D1)]), answer, splits=_splits_with_lost_element())
    summary = out.tables[0].summary
    assert summary.verdict == NoveltyVerdict.SUBSTANTIALLY_SAME_CANDIDATE
    assert "확인 못 한 구성요소 1개" in summary.reason


def test_진보성_차이점에_확인_못_한_구성요소가_대비하지_않음으로_남는다():
    answer = _answer([_row(1, "D1", "disclosed", (P23, FULL23))])
    out, _, _ = _run(_inventive(), answer, splits=_splits_with_lost_element())
    assert out.tables[0].summary.differences == [
        "청구항 1 [구성 1-2] (구성요소 글자를 확인하지 못해 대비하지 않음)"
    ]


@pytest.mark.parametrize("quote", ["습", "습도 센서"])
def test_너무_짧은_근거_글자는_검사_오류로_다시_부르고_그래도_짧으면_버린다(quote):
    short = _answer([_row(1, "D1", "disclosed", (P23, quote)), _row(2, "D1", "unclear")])
    out, calls, _ = _run(_inventive(), [short, short])
    assert len(calls) == 2 and "검사 오류" in calls[1]["prompt"]
    row = _find(out.tables[0], 1, "D1")
    assert row.evidence == [] and row.status.reason == UnverifiedReason.EVIDENCE_REJECTED


def test_조각_글_전체를_옮긴_근거는_짧아도_받는다():
    # 조각 글이 하한보다 짧으면(도면 설명 한 줄 등) 통째로 옮긴 것만 받는다
    whole = _answer(
        [_row(1, "D1", "unclear"), _row(2, "D1", "disclosed", (P31, "물통은 물을 담아 둔다"))]
    )
    out, calls, _ = _run(_inventive(), whole)
    assert len(calls) == 1
    assert _find(out.tables[0], 2, "D1").status.value == StatusValue.CONFIRMED


def test_신규성_차이_없음과_실질적_동일_후보에는_늘_직접_검토_필요가_붙는다():
    same = _answer(
        [
            _row(1, "D1", "disclosed", (P23, FULL23)),
            _row(2, "D1", "disclosed", (P31, "물통은 물을 담아 둔다")),
        ]
    )
    unclear = _answer([_row(1, "D1", "disclosed", (P23, FULL23)), _row(2, "D1", "unclear")])
    for answer, verdict in (
        (same, NoveltyVerdict.NO_DIFFERENCE),
        (unclear, NoveltyVerdict.SUBSTANTIALLY_SAME_CANDIDATE),
    ):
        out, _, _ = _run(_novelty([citation("D1", D1)]), answer)
        assert out.tables[0].summary.verdict == verdict
        assert Flag.NEEDS_HUMAN_REVIEW in out.tables[0].flags
    reason = out.tables[0].summary.reason
    assert "가리기 어려운 구성요소만 있음, 실질적 동일 판단 아님" in reason
    # 근거가 있는 "차이 있음"에도 붙는다: 요약 표시는 AI 정리일 뿐 신규성 결론이 아니다
    shown = _answer(
        [
            _row(1, "D1", "disclosed", (P23, FULL23)),
            _row(2, "D1", "difference_candidate", (P31, "물통은 물을 담아 둔다")),
        ]
    )
    different, _, _ = _run(_novelty([citation("D1", D1)]), shown)
    assert different.tables[0].summary.verdict == NoveltyVerdict.DIFFERENT
    assert Flag.NEEDS_HUMAN_REVIEW in different.tables[0].flags
    assert "판정 아님" in different.tables[0].summary.reason
    assert "못 찾은 것" not in different.tables[0].summary.reason  # 못 찾음 글은 그 경우에만


def test_못_찾음에서만_나온_차이_있음에는_직접_검토_필요와_판단_아님을_적는다():
    # 못 찾음 ≠ 없음: 차이 후보가 전부 "조회 범위 내 없음" 줄이면 사람이 보게 한다
    out, _, _ = _run(_novelty([citation("D1", D1)]), ONE_DIFFERENT)
    table = out.tables[0]
    assert table.summary.verdict == NoveltyVerdict.DIFFERENT
    assert Flag.NEEDS_HUMAN_REVIEW in table.flags
    assert "찾아본 범위에서 못 찾은 것, 없다는 판단 아님" in table.summary.reason


def test_독립항이_대상이_아닌_단위의_대비표에는_직접_검토_필요가_붙는다():
    claims = {1: CLAIMS[1], 2: "제1항에 있어서, 뚜껑을 더 포함하는 화분."}
    splits = {1: SPLITS[1], 2: split(2, ["뚜껑"], [1])}
    result = oa([rejection(1, "29-1-1", [2], [citation("D1", D1)])])
    config = _config()
    config = config.model_copy(
        update={"inputs": config.inputs.model_copy(update={"claims_at_oa": claims})}
    )
    out, _, _ = _run(
        result, _answer([_row(1, "D1", "difference_candidate")], claim=2), config, splits
    )
    (table,) = out.tables
    assert table.unit_id == "oa_1:29-1-1:c2" and {r.claim for r in table.rows} == {2}
    assert Flag.NEEDS_HUMAN_REVIEW in table.flags


def test_심사관_위치를_끄면_진보성_요약에_심사관_논리_원문을_넣지_않는다(caplog):
    answer = _answer([_row(1, "D1", "unclear"), _row(2, "D1", "unclear")])
    with caplog.at_level(logging.WARNING):
        out, _, _ = _run(_inventive(), answer, _config(use_examiner=False))
    combination = out.tables[0].summary.combination
    assert "D1에 D2를 결합" not in combination and combination.strip()
    assert any("결합 논리" in r.getMessage() for r in caplog.records)


def test_근거_글자_하한과_대비_호출_상한_설정():
    assert load_f3_settings().min_quote_chars == 10
    assert load_step_config("f3.compare").max_model_calls == 240


def test_모르는_검색_방식_이름은_조용히_바꾸지_않고_설정_오류로_멈춘다():
    config = _config()
    search = config.settings.search.model_copy(update={"impl": "fake"})
    settings = config.settings.model_copy(update={"search": search})
    with pytest.raises(ModelConfigError, match="fake"):
        _run(_inventive(), [], config.model_copy(update={"settings": settings}))


# ---- 대비할 문헌이 없는 청구항은 기록 없이 빠지지 않는다 ----
SPLITS_1_3 = {1: SPLITS[1], 3: split(3, [SENSOR], [1])}


def test_대비할_문헌이_없는_청구항은_보류와_경고를_남긴다(caplog):
    # 청구항 3의 줄은 D2만 적용했는데 D2는 JP라 대비할 수 없다
    result = oa(
        [rejection(1, "29-2", [1, 3], [citation("D1", D1), citation("D2", "JP1A", country="JP")])],
        [claim_row(1, 1, ["D1"]), claim_row(3, 1, ["D2"])],
    )
    answer = _answer([_row(1, "D1", "unclear"), _row(2, "D1", "unclear")])
    with caplog.at_level(logging.WARNING):
        out, _, _ = _run(result, answer, splits=SPLITS_1_3)
    (table,) = out.tables
    assert {r.claim for r in table.rows} == {1}
    held = [h for h in out.held_tasks if h.task.endswith(":claim3")]
    assert len(held) == 1 and held[0].task == f"f3_compare:{table.unit_id}:claim3"
    assert "청구항 3" in held[0].waiting_for
    assert any("청구항 3" in r.getMessage() for r in caplog.records)


def test_신규성은_다른_문헌_묶음에서_대비된_청구항은_보류하지_않는다():
    # 청구항 3은 D2에만 적용: D1 묶음에서는 비지만 D2 묶음에서 대비된다
    result = oa(
        [rejection(1, "29-1-1", [1, 3], [citation("D1", D1), citation("D2", D2)])],
        [claim_row(1, 1, ["D1", "D2"]), claim_row(3, 1, ["D2"])],
    )
    answers = [
        _answer([_row(1, "D1", "unclear"), _row(2, "D1", "unclear")]),
        _answer([_row(1, "D2", "unclear"), _row(2, "D2", "unclear")]),
        _answer([_row(1, "D2", "unclear")], claim=3),
    ]
    out, _, _ = _run(result, answers, splits=SPLITS_1_3)
    assert len(out.tables) == 2
    assert not [h for h in out.held_tasks if h.task.endswith(":claim3")]


def test_진보성_차이점_불명은_불명으로_적고_근거_있는_차이_후보는_꾸밈이_없다():
    unclear = _answer([_row(1, "D1", "disclosed", (P23, FULL23)), _row(2, "D1", "unclear")])
    out, _, _ = _run(_inventive(), unclear)
    assert out.tables[0].summary.differences == [f"청구항 1 [구성 1-2] {TANK} (불명)"]
    with_evidence = _answer(
        [
            _row(1, "D1", "disclosed", (P23, FULL23)),
            _row(2, "D1", "difference_candidate", (P31, "물통은 물을 담아 둔다")),
        ]
    )
    out, _, _ = _run(_inventive(), with_evidence)
    assert out.tables[0].summary.differences == [f"청구항 1 [구성 1-2] {TANK}"]


def test_진보성_차이점은_근거_있는_차이_후보_줄이_하나라도_있으면_꾸밈이_없다():
    # 구성 1-2: D1은 근거 없는 차이 후보, D2는 근거 있는 차이 후보
    cited = [citation("D1", D1), citation("D2", D2)]
    answer = _answer(
        [
            _row(1, "D1", "disclosed", (P23, FULL23)),
            _row(2, "D1", "difference_candidate"),
            _row(1, "D2", "unclear"),
            _row(2, "D2", "difference_candidate", (P10, "제어부는 밸브를 연다")),
        ]
    )
    out, _, _ = _run(_inventive(cited), answer)
    assert out.tables[0].summary.differences == [f"청구항 1 [구성 1-2] {TANK}"]
