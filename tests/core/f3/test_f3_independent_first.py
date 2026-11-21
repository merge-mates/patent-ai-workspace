"""진보성: 독립항 먼저 대비하고, 독립항이 무너진 묶음만 종속항을 따로 대비한다 (이슈 #30 C1).

"무너짐" = 대표(독립) 청구항 줄이 모두 개시됨 (design 3-3, 지금 규칙 그대로).
독립항에 차이 후보·불명이 있으면 종속항은 대비하지 않고 보류 `…:claim<N>:dependent`로 이유를 남긴다.
신규성은 이 순서를 쓰지 않는다 (청구항마다 따로 판정하므로 전부 대비).
모델 호출 수도 본다: 독립항이 안 무너지면 종속항 호출이 없다.
"""

import functools
import json

from patent_ai.core.f3_claim_compare.compare import STEP, compare_unit, make_searcher
from patent_ai.core.f3_claim_compare.config import load_f3_settings
from patent_ai.core.f3_claim_compare.inputs import F3Config, F3Inputs
from patent_ai.core.f3_claim_compare.units import build_units
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.common import StatusValue
from patent_ai.core.schemas.oa_result import RejectionKind
from patent_ai.retrieval.repository import InMemoryChunkRepository
from tests.core.f3 import scenario
from tests.core.f3.fakes import OK, citation, claim_row, oa, paragraph, rejection, split
from tests.core.f3.run_helpers import run_scenario

D1 = "KR20990000001A"
SENSOR, TANK, LID = "습도 센서", "물통", "뚜껑"
CLAIMS = {
    1: f"화분에 있어서, {SENSOR}; 및 {TANK}을 포함하는 화분.",
    3: f"제1항에 있어서, {LID}을 더 포함하는 화분.",
}
SPLITS = {1: split(1, [SENSOR, TANK]), 3: split(3, [LID], [1])}
CHUNKS = [
    paragraph(D1, 23, "습도 센서는 흙에 꽂혀 습도를 잰다", [1.0, 0.0]),
    paragraph(D1, 31, "물통은 물을 담아 둔다", [0.0, 1.0]),
]
P23, P31 = (c.chunk_id for c in CHUNKS)
FULL23, FULL31 = "습도 센서는 흙에 꽂혀 습도를 잰다", "물통은 물을 담아 둔다"
REPO = InMemoryChunkRepository({"cite": CHUNKS})
HELD = "f3_compare:oa_1:29-2:c1:claim3:dependent"


@functools.cache
def _searcher():
    return make_searcher(
        load_f3_settings(), REPO, lambda q: [1.0, 0.0] if "센서" in q else [0.0, 1.0]
    )


def _answer(claim: int, *rows) -> TransportResponse:
    made = [
        {
            "element_no": no,
            "citation": "D1",
            "judgment": judgment,
            "evidence": [{"chunk_id": c, "quote": q} for c, q in evidence],
        }
        for no, judgment, *evidence in rows
    ]
    return TransportResponse(json.dumps({"claim": claim, "rows": made}, ensure_ascii=False), 1, 1)


ALL_DISCLOSED = _answer(1, (1, "disclosed", (P23, FULL23)), (2, "disclosed", (P31, FULL31)))
LID_ANSWER = _answer(3, (1, "difference_candidate"))


def _run(kind: str, answers, splits=None):
    article = "29-2" if kind == "inventive" else "29-1-1"
    result = oa([rejection(1, article, [1, 3], [citation("D1", D1)])])
    settings = load_f3_settings().model_copy(update={"second_search": False})
    inputs = F3Inputs(claims_at_oa=CLAIMS, claims_status=OK, claims_document_id="d_c")
    config = F3Config(settings=settings, inputs=inputs)
    transport = FakeTransport({STEP: answers})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    splits = splits or SPLITS
    units, _ = build_units(result, splits)
    out = compare_unit(units[0], result, splits, config, ctx=ctx, searcher=_searcher(), repo=REPO)
    return out, transport.calls


def _held(out, task):
    return next((h for h in out.held_tasks if h.task == task), None)


def test_독립항에_차이_후보가_있으면_종속항은_대비하지_않고_모델도_부르지_않는다():
    two = _answer(1, (1, "disclosed", (P23, FULL23)), (2, "difference_candidate"))
    out, calls = _run("inventive", [two, LID_ANSWER])
    assert len(calls) == 1  # 독립항 한 번 (이전에는 청구항마다 2번)
    (table,) = out.tables
    assert {r.claim for r in table.rows} == {1}


def test_독립항에_차이가_있어_빼면_이유가_보류로_남고_그_이유에_독립항이_나온다():
    two = _answer(1, (1, "disclosed", (P23, FULL23)), (2, "difference_candidate"))
    out, _ = _run("inventive", [two, LID_ANSWER])
    held = _held(out, HELD)
    assert held is not None
    assert "청구항 1" in held.waiting_for and "대비하지 않음" in held.waiting_for


def test_독립항이_불명이어도_개시됨이_아니라서_종속항은_대비하지_않는다():
    out, calls = _run("inventive", [_answer(1, (1, "unclear"), (2, "unclear")), LID_ANSWER])
    assert len(calls) == 1
    assert _held(out, HELD) is not None


def test_독립항이_모두_개시됨이면_종속항을_따로_대비한다():
    out, calls = _run("inventive", [ALL_DISCLOSED, LID_ANSWER])
    assert len(calls) == 2
    (table,) = out.tables
    assert {r.claim for r in table.rows} == {1, 3}
    assert _held(out, HELD) is None
    # 부모(청구항 1)는 이미 대비됐으니 종속항 줄에 부모 구성요소를 다시 넣지 않는다 (11/21 결정)
    assert [r.element_location for r in table.rows if r.claim == 3] == ["청구항 3 [구성 3-1]"]


def test_신규성은_독립항이_안_무너져도_청구항을_모두_대비한다():
    two = _answer(1, (1, "disclosed", (P23, FULL23)), (2, "difference_candidate"))
    out, calls = _run("novelty", [two, LID_ANSWER])
    assert len(calls) == 2
    assert {r.claim for r in out.tables[0].rows} == {1, 3}
    assert all(not h.task.endswith(":dependent") for h in out.held_tasks)


def test_독립항을_대비할_수_없으면_종속항을_조용히_빼지_않고_그대로_대비한다():
    # 독립항 구성요소가 비어 독립항 줄이 없다: 무너졌는지 알 수 없으므로 종속항 대비는 그대로
    splits = {1: split(1, []), 3: split(3, [LID], [1])}
    out, calls = _run("inventive", [LID_ANSWER], splits=splits)
    assert len(calls) == 1
    assert {r.claim for r in out.tables[0].rows} == {3}
    assert _held(out, HELD) is None


def test_대표_청구항이_진보성_단위_종류다():
    # 위 테스트가 기대는 단위 모양: 독립항 1이 대표, claims [1, 3]
    result = oa([rejection(1, "29-2", [1, 3], [citation("D1", D1)])])
    units, _ = build_units(result, SPLITS)
    assert units[0].rejection_kind == RejectionKind.INVENTIVE_STEP
    assert (units[0].representative_claim, units[0].claims) == (1, [1, 3])


def test_종속항을_대비하지_않은_보류는_결과_전체_status를_확인되지_않음으로_낮추지_않는다():
    answers = scenario.responses()
    # 독립항 청구항 1의 물통이 차이 후보: 청구항 2(종속항)는 대비하지 않는다
    answers["f3.compare"] = [
        scenario._text(
            {
                "claim": 1,
                "rows": [
                    scenario._row(
                        1, "disclosed", (scenario.P23, "습도 센서는 흙에 꽂혀 습도를 잰다")
                    ),
                    scenario._row(2, "difference_candidate"),
                ],
            }
        )
    ]
    result, transport = run_scenario(answers=answers)
    assert [h.task for h in result.held_tasks] == ["f3_compare:oa_1:29-2:c1:claim2:dependent"]
    assert sum(1 for c in transport.calls if c["step"] == "f3.compare") == 1
    # 건너뜀은 기다리는 자료가 없는 정해진 일이라 status는 대비표가 정한다 (못 찾음)
    assert result.status.value == StatusValue.NOT_FOUND_IN_SCOPE


# ---- 대표 청구항이 독립항이 아니거나 종속항에만 문헌이 더 붙은 묶음 (코드 리뷰 고침) ----
HANDLE = "손잡이"
D2 = "KR20990000002A"


def _run_general(result, splits, claims, answers, repo=REPO, searcher=None):
    settings = load_f3_settings().model_copy(update={"second_search": False})
    inputs = F3Inputs(claims_at_oa=claims, claims_status=OK, claims_document_id="d_c")
    transport = FakeTransport({STEP: answers})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    units, _ = build_units(result, splits)
    out = compare_unit(
        units[0],
        result,
        splits,
        F3Config(settings=settings, inputs=inputs),
        ctx=ctx,
        searcher=searcher or _searcher(),
        repo=repo,
    )
    return out, transport.calls, units[0]


def _many(claim: int, n: int, judgment="unclear") -> TransportResponse:
    return _answer(claim, *[(i, judgment) for i in range(1, n + 1)])


def test_대표가_종속항이어도_대표를_인용하지_않는_형제_종속항은_건너뛰지_않는다():
    # 1은 독립항(이 거절이유의 대상 아님), 2·3은 둘 다 1을 인용하는 진보성 대상. 대표는 2
    splits = {1: SPLITS[1], 2: split(2, [LID], [1]), 3: split(3, [HANDLE], [1])}
    claims = {**CLAIMS, 2: "제1항에 있어서, 뚜껑을 더 포함", 3: "제1항에 있어서, 손잡이를 더 포함"}
    result = oa([rejection(1, "29-2", [2, 3], [citation("D1", D1)])])
    out, calls, unit = _run_general(result, splits, claims, [_many(2, 3), _many(3, 3)])
    assert unit.representative_claim == 2
    assert len(calls) == 2  # 2가 안 무너져도 형제 3은 2의 구성요소를 갖지 않으므로 대비한다
    assert {r.claim for r in out.tables[0].rows} == {2, 3}
    assert not any(h.task.endswith(":dependent") for h in out.held_tasks)


def test_건너뛴_종속항의_이유_글은_대표_청구항이라고_사실대로_적는다():
    # 대표 2(종속항)가 안 무너지고, 2를 인용하는 4는 2의 구성요소를 모두 가지므로 건너뛴다
    splits = {1: SPLITS[1], 2: split(2, [LID], [1]), 4: split(4, [HANDLE], [2])}
    claims = {**CLAIMS, 2: "제1항에 있어서, 뚜껑을 더 포함", 4: "제2항에 있어서, 손잡이를 더 포함"}
    result = oa([rejection(1, "29-2", [2, 4], [citation("D1", D1)])])
    out, calls, _ = _run_general(result, splits, claims, [_many(2, 3), _many(4, 4)])
    assert len(calls) == 1
    (held,) = [h for h in out.held_tasks if h.task.endswith(":claim4:dependent")]
    assert "대표 청구항 2" in held.waiting_for and "독립항" not in held.waiting_for


def test_종속항에만_문헌이_더_붙었으면_독립항에_차이가_있어도_건너뛰지_않는다():
    # 청구항 1은 D1, 3은 D1·D2. 1의 구성요소는 D2와 아직 대비되지 않았다 (11/21 결정)
    chunks = [
        paragraph(D1, 23, "습도 센서는 흙에 꽂혀 습도를 잰다", [1.0, 0.0]),
        paragraph(D2, 7, "센서와 물통이 있다", [0.0, 1.0]),
    ]
    repo = InMemoryChunkRepository({"cite": chunks})
    searcher = make_searcher(load_f3_settings(), repo, lambda q: [1.0, 0.0])
    result = oa(
        [rejection(1, "29-2", [1, 3], [citation("D1", D1), citation("D2", D2)])],
        [claim_row(1, 1, ["D1"]), claim_row(3, 1, ["D1", "D2"])],
    )

    def raw(claim, pairs):
        made = [
            {"element_no": n, "citation": c, "judgment": "unclear", "evidence": []}
            for n, c in pairs
        ]
        body = {"claim": claim, "rows": made}
        return TransportResponse(json.dumps(body, ensure_ascii=False), 1, 1)

    both = [(n, c) for n in (1, 2, 3) for c in ("D1", "D2")]
    answers = [raw(1, [(1, "D1"), (2, "D1")]), raw(3, both)]
    out, calls, _ = _run_general(result, SPLITS, CLAIMS, answers, repo, searcher)
    assert len(calls) == 2  # 독립항이 안 무너져도 청구항 3을 대비한다
    d2_rows = [r for r in out.tables[0].rows if r.claim == 3 and r.citation == "D2"]
    assert [r.element_location for r in d2_rows][:2] == [
        "청구항 1 [구성 1-1]",
        "청구항 1 [구성 1-2]",
    ]
    assert not any(h.task.endswith(":dependent") for h in out.held_tasks)


def test_건너뛴_청구항을_부모로_보지_않아_가지_종속항이_그_구성요소를_대비한다():
    # 1은 안 무너짐, 2(1 인용)는 건너뜀, 3은 "제1항 또는 제2항"이라 가지: 건너뛰지 않는다.
    # 건너뛴 2는 대비되지 않았으므로 3이 2의 구성요소를 대비된 것으로 보면 안 된다
    splits = {
        1: SPLITS[1],
        2: split(2, [LID], [1]),
        3: split(3, [HANDLE], [1, 2]),
    }
    claims = {**CLAIMS, 2: "제1항에 있어서, 뚜껑", 3: "제1항 또는 제2항에 있어서, 손잡이"}
    result = oa([rejection(1, "29-2", [1, 2, 3], [citation("D1", D1)])])
    two = _answer(1, (1, "disclosed", (P23, FULL23)), (2, "difference_candidate"))
    out, calls, _ = _run_general(result, splits, claims, [two, _many(3, 1)])
    assert len(calls) == 2  # 청구항 1, 3 (2는 건너뜀)
    unit = "oa_1:29-2:c1"
    tasks = [h.task for h in out.held_tasks]
    assert f"f3_compare:{unit}:claim2:dependent" in tasks
    # 3은 부모 2의 구성요소를 빌리지 못하는 가지라 가지 보류가 남는다 (조용히 빠지지 않음)
    assert f"f3_compare:{unit}:claim3:branch" in tasks
