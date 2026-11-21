"""진보성 요약 ③ 명세서 효과 반박 후보 (이슈 #30 C2).

차이점 구성요소마다 최초 명세서에서 효과 문장을 모델이 뽑고, 코드가 그 문장이 명세서 쪽 글자에
그대로 있는지 확인한다. 있으면 `[식별번호] 문장 (관련 차이점: 위치)`, 명세서 어디에도 없으면
후보에서 빼고 보류 `…:effect`로 건수만 남긴다. 명세서가 없으면 후보를 못 뽑고 본문 미확보 보류를
남긴다(OA 단위 `f3_compare:<oa_id>:spec`와 진보성 단위 `f3_compare:<unit_id>:spec`).
기대 모양은 이슈 #30 task C2와 design 3-2 기준이다.
"""

import functools
import json
import logging

from patent_ai.core.f3_claim_compare.compare import STEP, compare_unit, make_searcher
from patent_ai.core.f3_claim_compare.config import load_f3_settings
from patent_ai.core.f3_claim_compare.inputs import F3Config, F3Inputs
from patent_ai.core.f3_claim_compare.units import build_units
from patent_ai.core.llm.config import load_step_config
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportError, TransportResponse
from patent_ai.core.schemas.common import UnverifiedReason
from patent_ai.core.schemas.document import Page, PageText
from patent_ai.retrieval.repository import InMemoryChunkRepository
from tests.core.f3 import scenario
from tests.core.f3.fakes import OK, citation, oa, paragraph, rejection, split
from tests.core.f3.run_helpers import run_scenario

EFFECT = "f3.effect"
D1 = "KR20990000001A"
SENSOR, TANK = "습도 센서", "물통"
CLAIMS = {1: f"화분에 있어서, {SENSOR}; 및 {TANK}을 포함하는 화분."}
SPLITS = {1: split(1, [SENSOR, TANK])}
CHUNKS = [
    paragraph(D1, 23, "습도 센서는 흙에 꽂혀 습도를 잰다", [1.0, 0.0]),
    paragraph(D1, 31, "물통은 물을 담아 둔다", [0.0, 1.0]),
]
P23, P31 = (c.chunk_id for c in CHUNKS)
REPO = InMemoryChunkRepository({"cite": CHUNKS})
EFFECT_TEXT = "물통이 물을 담아 두어 화분의 급수 간격을 늘리는 효과가 있다"
SPEC = PageText(
    document_id="d_spec",
    status=OK,
    pages=[
        Page(
            page=1,
            status=OK,
            text=f"【0015】 본 발명은 화분에 관한 것이다.\n【0016】 {EFFECT_TEXT}.",
        )
    ],
)
SPEC_P16 = "cite-spec-memory:d_spec:pg1:p0016"


@functools.cache
def _searcher():
    return make_searcher(
        load_f3_settings(), REPO, lambda q: [1.0, 0.0] if "센서" in q else [0.0, 1.0]
    )


def _compare(*rows) -> TransportResponse:
    made = [
        {
            "element_no": no,
            "citation": "D1",
            "judgment": judgment,
            "evidence": [{"chunk_id": c, "quote": q} for c, q in evidence],
        }
        for no, judgment, *evidence in rows
    ]
    return TransportResponse(json.dumps({"claim": 1, "rows": made}, ensure_ascii=False), 1, 1)


SENSOR_OK = (1, "disclosed", (P23, "습도 센서는 흙에 꽂혀 습도를 잰다"))
TANK_DIFF = (2, "difference_candidate")
TANK_OK = (2, "disclosed", (P31, "물통은 물을 담아 둔다"))


def _effects(*picks) -> TransportResponse:
    made = [{"difference_no": n, "chunk_id": c, "quote": q} for n, c, q in picks]
    return TransportResponse(json.dumps({"effects": made}, ensure_ascii=False), 1, 1)


def _run(answers, spec=SPEC, effect_limit=None):
    result = oa([rejection(1, "29-2", [1], [citation("D1", D1)])])
    settings = load_f3_settings().model_copy(update={"second_search": False})
    inputs = F3Inputs(claims_at_oa=CLAIMS, claims_status=OK, claims_document_id="d_c", spec=spec)
    transport = FakeTransport(answers)
    budget = CallBudget()
    if effect_limit is not None:
        # 효과 단계 호출을 이미 상한(config 80)만큼 쓴 실행
        for _ in range(load_step_config(EFFECT).max_model_calls):
            budget.add("r_1", EFFECT, 0)
    ctx = RunContext(run_id="r_1", budget=budget, recorder=MemoryRecorder(), transport=transport)
    units, _ = build_units(result, SPLITS)
    out = compare_unit(
        units[0],
        result,
        SPLITS,
        F3Config(settings=settings, inputs=inputs),
        ctx=ctx,
        searcher=_searcher(),
        repo=REPO,
    )
    return out, transport


def _effect_calls(transport):
    return [c for c in transport.calls if c["step"] == EFFECT]


def test_차이점의_효과_문장이_명세서_글자에_그대로_있으면_위치와_함께_후보가_된다():
    out, _ = _run(
        {STEP: [_compare(SENSOR_OK, TANK_DIFF)], EFFECT: [_effects((1, SPEC_P16, EFFECT_TEXT))]}
    )
    (table,) = out.tables
    # 차이점은 물통 하나 (차이점 1번)
    assert table.summary.effect_candidates == [
        f"[0016] {EFFECT_TEXT} (관련 차이점: 청구항 1 [구성 1-2])"
    ]


def test_효과_문장이_명세서_어디에도_그대로_없으면_후보에_넣지_않고_건수만_보류로_남긴다():
    wrong = "물통이 급수 간격을 열 배로 늘린다"  # 명세서에 없는 문장
    out, transport = _run(
        {
            STEP: [_compare(SENSOR_OK, TANK_DIFF)],
            EFFECT: [_effects((1, SPEC_P16, wrong)), _effects((1, SPEC_P16, wrong))],
        }
    )
    (table,) = out.tables
    assert table.summary.effect_candidates == []  # 지어낸 근거를 싣지 않는다
    assert len(_effect_calls(transport)) == 2  # 검사에 떨어져 한 번 다시 불렀다
    held = next(h for h in out.held_tasks if h.task == "f3_compare:oa_1:29-2:c1:effect")
    assert "1건" in held.waiting_for and wrong not in held.waiting_for  # 원문 글자 없이


def test_모델이_다른_조각을_골라도_명세서_전체에서_찾으면_맞는_위치로_싣고_다시_부르지_않는다():
    out, transport = _run(
        {
            STEP: [_compare(SENSOR_OK, TANK_DIFF)],
            # 후보에 없는 조각 번호를 골랐지만 문장은 [0016]에 그대로 있다
            EFFECT: [_effects((1, "cite-spec-memory:d_spec:pg1:p9999", EFFECT_TEXT))],
        }
    )
    assert out.tables[0].summary.effect_candidates == [
        f"[0016] {EFFECT_TEXT} (관련 차이점: 청구항 1 [구성 1-2])"
    ]
    assert len(_effect_calls(transport)) == 1
    assert all(h.task != "f3_compare:oa_1:29-2:c1:effect" for h in out.held_tasks)


def test_쪽을_넘어_이어진_문장도_명세서_전체에서_찾는다():
    head, tail = "물통이 물을 담아 두어 화분의", "급수 간격을 늘리는 효과가 있다."
    spec = PageText(
        document_id="d_spec",
        status=OK,
        pages=[
            Page(page=1, status=OK, text=f"【0016】 {head}"),
            Page(page=2, status=OK, text=tail),
        ],
    )
    sentence = f"{head} {tail}"
    out, _ = _run(
        {STEP: [_compare(SENSOR_OK, TANK_DIFF)], EFFECT: [_effects((1, SPEC_P16, sentence))]},
        spec=spec,
    )
    assert out.tables[0].summary.effect_candidates == [
        f"[0016] {sentence} (관련 차이점: 청구항 1 [구성 1-2])"
    ]


def test_효과_문장을_못_뽑으면_빈_목록이고_있지도_않은_후보를_만들지_않고_경고한다(caplog):
    with caplog.at_level(logging.WARNING):
        out, _ = _run({STEP: [_compare(SENSOR_OK, TANK_DIFF)], EFFECT: [_effects()]})
    assert out.tables[0].summary.effect_candidates == []
    # 빈 목록이 조용히 지나가지 않는다: 못 찾은 것이지 없다는 판단이 아님
    assert any("효과 문장을 못 찾음" in r.getMessage() for r in caplog.records)


def test_차이점이_없으면_효과를_뽑는_모델을_부르지_않는다():
    out, transport = _run({STEP: [_compare(SENSOR_OK, TANK_OK)]})
    assert out.tables[0].summary.effect_candidates == []
    assert _effect_calls(transport) == []


def test_최초_명세서가_없으면_모델을_부르지_않고_본문_미확보_보류를_남긴다():
    out, transport = _run({STEP: [_compare(SENSOR_OK, TANK_DIFF)]}, spec=None)
    assert out.tables[0].summary.effect_candidates == []
    assert _effect_calls(transport) == []
    held = next(h for h in out.held_tasks if h.task == "f3_compare:oa_1:spec")
    assert "최초 명세서" in held.waiting_for
    # 진보성 단위 보류도 같이 남는다 (F4가 그 묶음 후보 확인 사항에 싣는다)
    unit_held = next(h for h in out.held_tasks if h.task == "f3_compare:oa_1:29-2:c1:spec")
    assert "최초 명세서" in unit_held.waiting_for


def test_명세서_보류는_run_f3에서_본문_미확보로_센다():
    config = scenario.config()
    no_spec = config.model_copy(update={"inputs": config.inputs.model_copy(update={"spec": None})})
    result, _ = run_scenario(config=no_spec)
    assert any(h.task == "f3_compare:oa_1:spec" for h in result.held_tasks)
    assert result.status.value.value == "unverified"
    assert result.status.reason == UnverifiedReason.BODY_MISSING
    # 단위 보류(`…:c1:spec`)도 본문 미확보로 센다
    assert any(h.task == "f3_compare:oa_1:29-2:c1:spec" for h in result.held_tasks)


def test_효과_뽑기_호출이_실패해도_대비표는_남기고_효과_후보만_빈_목록으로_보류한다():
    out, _ = _run(
        {
            STEP: [_compare(SENSOR_OK, TANK_DIFF)],
            EFFECT: [TransportError("연결 끊김", retryable=False)],
        }
    )
    (table,) = out.tables
    assert table.summary.effect_candidates == [] and table.rows
    task = "f3_compare:oa_1:29-2:c1:effect:call_failed"
    held = next(h for h in out.held_tasks if h.task == task)
    assert "ModelCallFailed" in held.waiting_for
    assert out.call_errors == []  # 대비 단계가 못 돈 것이 아니다 (표가 나왔다)


def test_효과_뽑기가_호출_상한에_닿아도_대비표는_남기고_limit_reached로_보류한다():
    out, _ = _run({STEP: [_compare(SENSOR_OK, TANK_DIFF)], EFFECT: []}, effect_limit=0)
    assert out.tables
    assert any(h.task == "f3_compare:oa_1:29-2:c1:effect:limit_reached" for h in out.held_tasks)


def test_효과_단계에_호출_상한과_프롬프트_파일과_자기_조각_수_칸이_있다():
    cfg = load_step_config(EFFECT)
    assert cfg.max_model_calls is not None
    assert load_f3_settings().effect_search.k == 5  # clarity_search.k를 빌려 쓰지 않는다
    assert cfg.prompt == "prompts/f3/effect.md"


def test_신규성_표에는_효과_단계를_돌리지_않는다():
    result = oa([rejection(1, "29-1-1", [1], [citation("D1", D1)])])
    settings = load_f3_settings().model_copy(update={"second_search": False})
    inputs = F3Inputs(claims_at_oa=CLAIMS, claims_status=OK, claims_document_id="d_c", spec=SPEC)
    transport = FakeTransport({STEP: [_compare(SENSOR_OK, TANK_DIFF)]})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    units, _ = build_units(result, SPLITS)
    out = compare_unit(
        units[0],
        result,
        SPLITS,
        F3Config(settings=settings, inputs=inputs),
        ctx=ctx,
        searcher=_searcher(),
        repo=REPO,
    )
    assert _effect_calls(transport) == []
    assert out.tables[0].summary.kind == "novelty"


def test_모델에는_차이점과_명세서_후보_조각을_준다():
    _, transport = _run(
        {STEP: [_compare(SENSOR_OK, TANK_DIFF)], EFFECT: [_effects((1, SPEC_P16, EFFECT_TEXT))]}
    )
    (call,) = _effect_calls(transport)
    assert TANK in call["prompt"] and EFFECT_TEXT in call["prompt"]
    assert SPEC_P16 in call["prompt"]
