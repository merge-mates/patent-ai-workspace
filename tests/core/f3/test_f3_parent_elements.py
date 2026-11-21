"""부모 청구항의 구성요소를 종속항 대비에 넣기 (11/21 재아 결정).

독립항이 그 거절이유의 대상이 아니어도, 종속항은 인용하는 앞 청구항의 특징을 모두 포함하므로
(심사기준 5204쪽, docs/product/domain/신규성.md) 종속항 대비에 부모 구성요소를 같이 넣는다.
줄의 claim은 대비 대상인 종속항 번호, element_location은 그 구성요소가 실제로 있는 청구항이다.
부모가 같은 단위 안에 있으면(이미 대비됨) 다시 넣지 않는다.
"""

import functools
import json
import logging

from patent_ai.core.f3_claim_compare.compare import STEP, compare_unit, compare_units, make_searcher
from patent_ai.core.f3_claim_compare.config import load_f3_settings
from patent_ai.core.f3_claim_compare.inputs import F3Config, F3Inputs
from patent_ai.core.f3_claim_compare.units import build_units
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.common import Flag, StatusValue, UnverifiedReason
from patent_ai.core.schemas.comparison import ParagraphSource
from patent_ai.retrieval.repository import InMemoryChunkRepository
from tests.core.f3.fakes import OK, citation, claim_row, oa, paragraph, rejection, split

D1 = "KR20990000001A"
SENSOR, TANK, LID, HANDLE, BASE = "습도 센서", "물통", "뚜껑", "손잡이", "받침"
CLAIMS = {
    1: f"화분에 있어서, {SENSOR}; 및 {TANK}을 포함하는 화분.",
    3: f"제1항에 있어서, {LID}을 더 포함하는 화분.",
    4: f"제3항에 있어서, {HANDLE}를 더 포함하는 화분.",
    5: f"제1항에 있어서, {BASE}을 더 포함하는 화분.",
}
# 1은 독립항, 3·5는 1을, 4는 3을 인용한다
SPLITS = {
    1: split(1, [SENSOR, TANK]),
    3: split(3, [LID], [1]),
    4: split(4, [HANDLE], [3]),
    5: split(5, [BASE], [1]),
}
CHUNKS = [
    paragraph(D1, 23, "습도 센서는 흙에 꽂혀 습도를 잰다", [1.0, 0.0]),
    paragraph(D1, 31, "물통은 물을 담아 둔다", [0.0, 1.0]),
    paragraph(D1, 40, "뚜껑 아래 수조가 있다", [0.5, 0.5]),
]
P23, P31, P40 = (c.chunk_id for c in CHUNKS)
REPO = InMemoryChunkRepository({"cite": CHUNKS})
FULL23, FULL31 = "습도 센서는 흙에 꽂혀 습도를 잰다", "물통은 물을 담아 둔다"


@functools.cache
def _inner():
    return make_searcher(
        load_f3_settings(), REPO, lambda q: [1.0, 0.0] if "센서" in q else [0.0, 1.0]
    )


class _Recorder:
    def __init__(self):
        self.calls: list[str] = []

    def search(self, query, corpus, mode, k, doc_ids=None, as_of=None):
        self.calls.append(query)
        return _inner().search(query, corpus, mode, k, doc_ids=doc_ids, as_of=as_of)


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
    return TransportResponse(
        json.dumps({"claim": claim, "rows": made}, ensure_ascii=False), 100, 50
    )


def _config(use_examiner=True, claims=None) -> F3Config:
    settings = load_f3_settings()
    settings = settings.model_copy(
        update={
            "use_examiner_paragraphs": use_examiner,
            "search": settings.search.model_copy(update={"k": 1}),
        }
    )
    inputs = F3Inputs(claims_at_oa=claims or CLAIMS, claims_status=OK, claims_document_id="d_c")
    return F3Config(settings=settings, inputs=inputs)


def _run(result, responses, *, unit_index=0, splits=None, config=None, whole=False):
    splits = splits or SPLITS
    transport = FakeTransport({STEP: responses})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    searcher = _Recorder()
    units, _ = build_units(result, splits)
    args = (result, splits, config or _config())
    if whole:
        out = compare_units(units, *args, ctx=ctx, searcher=searcher, repo=REPO)
    else:
        out = compare_unit(units[unit_index], *args, ctx=ctx, searcher=searcher, repo=REPO)
    return out, transport.calls, searcher.calls, units


def _locations(table, claim: int) -> list[str]:
    return [r.element_location for r in table.rows if r.claim == claim]


# 청구항 1은 신규성, 3~5는 진보성 대상 (독립항 1은 진보성 거절이유의 대상이 아니다)
MIXED = oa(
    [
        rejection(1, "29-1-1", [1], [citation("D1", D1)]),
        rejection(2, "29-2", [3, 4, 5], [citation("D1", D1)]),
    ]
)
# 진보성 단위의 모델 답: 청구항 3(부모 1의 구성요소 2개 + 자기 1개), 4(자기 것만),
# 5(부모 2개 + 자기)
ANSWERS = [
    _answer(3, (1, "disclosed", (P23, FULL23)), (2, "difference_candidate"), (3, "unclear")),
    _answer(4, (1, "unclear")),
    _answer(5, (1, "disclosed", (P23, FULL23)), (2, "disclosed", (P31, FULL31)), (3, "unclear")),
]


def test_독립항이_대상이_아니어도_종속항_대비에_부모_구성요소가_들어간다():
    out, calls, _, units = _run(MIXED, ANSWERS, unit_index=1)
    unit = units[1]
    assert (unit.unit_id, unit.claims) == ("oa_1:29-2:c3", [3, 4, 5])
    (table,) = out.tables
    # 줄의 claim은 종속항 3, 위치는 구성요소가 실제로 있는 청구항 1
    assert _locations(table, 3) == [
        "청구항 1 [구성 1-1]",
        "청구항 1 [구성 1-2]",
        "청구항 3 [구성 3-1]",
    ]
    inherited = [
        r for r in table.rows if r.claim == 3 and r.element_location.startswith("청구항 1")
    ]
    assert [r.element for r in inherited] == [SENSOR, TANK]
    assert {r.claim for r in table.rows} == {3, 4, 5}  # 청구항 1의 줄은 따로 만들지 않는다
    # 모델에도 부모 구성요소와 부모 청구항 글자를 같이 보여 준다
    assert SENSOR in calls[0]["prompt"] and CLAIMS[1] in calls[0]["prompt"]


def test_부모가_같은_단위_안에서_이미_대비되면_다시_넣지_않는다():
    out, calls, _, _ = _run(MIXED, ANSWERS, unit_index=1)
    (table,) = out.tables
    # 4 → 3 → 1: 청구항 3이 단위 안에 있고 1의 구성요소도 3의 줄로 대비된다. 4는 자기 것만
    assert _locations(table, 4) == ["청구항 4 [구성 4-1]"]
    assert SENSOR not in calls[1]["prompt"].split("구성요소 (번호: 글자)")[1].split("후보 문단")[0]
    # 5 → 1: 단위 안에 1을 실어 주는 부모가 없어 5도 1의 구성요소를 싣는다
    assert _locations(table, 5) == [
        "청구항 1 [구성 1-1]",
        "청구항 1 [구성 1-2]",
        "청구항 5 [구성 5-1]",
    ]


def test_독립항이_같은_단위에_있는_평소_묶음은_종속항에_부모_줄이_없다():
    result = oa([rejection(1, "29-2", [1, 3], [citation("D1", D1)])])
    answers = [
        _answer(1, (1, "disclosed", (P23, FULL23)), (2, "disclosed", (P31, FULL31))),
        _answer(3, (1, "unclear")),
    ]
    out, _, _, _ = _run(result, answers)
    (table,) = out.tables
    assert _locations(table, 1) == ["청구항 1 [구성 1-1]", "청구항 1 [구성 1-2]"]
    assert _locations(table, 3) == ["청구항 3 [구성 3-1]"]


def test_여러_단계로_인용하면_거슬러_올라간_부모를_모두_넣는다():
    result = oa([rejection(1, "29-2", [4], [citation("D1", D1)])])  # 4 → 3 → 1, 대상은 4뿐
    answer = _answer(
        4, (1, "disclosed", (P23, FULL23)), (2, "unclear"), (3, "unclear"), (4, "unclear")
    )
    out, _, _, _ = _run(result, [answer])
    (table,) = out.tables
    assert _locations(table, 4) == [
        "청구항 1 [구성 1-1]",
        "청구항 1 [구성 1-2]",
        "청구항 3 [구성 3-1]",
        "청구항 4 [구성 4-1]",
    ]


def test_요약은_부모에서_온_구성요소도_그_종속항의_것으로_센다():
    out, _, _, _ = _run(MIXED, ANSWERS, unit_index=1)
    differences = out.tables[0].summary.differences
    # 청구항 3에서는 부모의 물통이 차이 후보였다. 청구항 5에서는 개시됨이라 빠진다
    assert f"청구항 1 [구성 1-2] {TANK} (청구항 3이 인용)" in differences
    assert not any("청구항 5이 인용" in d for d in differences)
    assert f"청구항 3 [구성 3-1] {LID}" in differences


def test_독립항이_대상_밖이라는_이유로는_경고도_표시도_따로_붙이지_않는다(caplog):
    with caplog.at_level(logging.WARNING):
        _, _, _, units = _run(MIXED, ANSWERS, unit_index=1)
    assert units[1].flags == [] and units[1].status.value == StatusValue.CONFIRMED
    assert not any("독립항" in r.getMessage() for r in caplog.records)


def test_검색_기록에_구성요소가_있는_청구항이_남고_같은_검색은_다시_하지_않는다():
    out, _, searches, _ = _run(MIXED, ANSWERS, unit_index=1)
    told = [(log.claim, log.element_claim, log.element_no) for log in out.search_log]
    assert told == [(3, 1, 1), (3, 1, 2), (3, 3, 1), (4, 4, 1), (5, 1, 1), (5, 1, 2), (5, 5, 1)]
    # 청구항 5에서 부모 구성요소(센서·물통)는 청구항 3 때 찾은 결과를 다시 쓴다
    assert searches == [SENSOR, TANK, LID, HANDLE, BASE]


def test_여러_단위에_걸쳐도_같은_검색은_한_번만_한다():
    # 신규성 단위(청구항 1)와 진보성 단위(3~5)가 같은 구성요소를 같은 문헌에서 찾는다
    first = _answer(1, (1, "disclosed", (P23, FULL23)), (2, "disclosed", (P31, FULL31)))
    _, _, searches, _ = _run(MIXED, [first, *ANSWERS], whole=True)
    assert searches == [SENSOR, TANK, LID, HANDLE, BASE]


def test_심사관_위치를_꺼도_부모_구성요소_대비에_누출이_없다():
    result = oa(
        [rejection(1, "29-2", [3], [citation("D1", D1)])],
        [claim_row(3, 1, ["D1"], {"D1": ["[0040]"]})],
    )
    answer = _answer(3, (1, "unclear"), (2, "unclear"), (3, "unclear"))
    out, calls, searches, _ = _run(result, [answer], config=_config(use_examiner=False))
    # 심사관 위치([0040])는 질의에도 후보에도 지정으로 들어가지 않는다 (조각 자체는 구성요소 검색에
    # 걸릴 수 있어 글자로는 가리지 않는다)
    assert all("0040" not in q for q in searches)
    assert out.examiner_locations == []
    assert all(r.paragraph_source == ParagraphSource.AI_FOUND for r in out.tables[0].rows)


def test_부모_청구항을_나누지_못했으면_부모_구성요소_없이_확인되지_않음으로_남긴다():
    # 청구항 1의 글자가 없어 나눈 결과가 없다: 3의 묶음을 정할 수 없다
    splits = {3: SPLITS[3]}
    result = oa([rejection(1, "29-2", [3], [citation("D1", D1)])])
    out, _, _, units = _run(result, [_answer(3, (1, "unclear"))], splits=splits)
    assert units[0].status.reason == UnverifiedReason.INPUT_UNVERIFIED
    assert _locations(out.tables[0], 3) == ["청구항 3 [구성 3-1]"]
    assert Flag.NEEDS_HUMAN_REVIEW in out.tables[0].flags


def test_부모의_인용_관계를_모르면_부모_구성요소를_넣지_않는다():
    splits = {**SPLITS, 3: split(3, [LID], None)}  # 3이 누구를 인용하는지 확인 못 함
    result = oa([rejection(1, "29-2", [4], [citation("D1", D1)])])
    out, _, _, units = _run(result, [_answer(4, (1, "unclear"))], splits=splits)
    assert units[0].status.reason == UnverifiedReason.INPUT_UNVERIFIED
    assert _locations(out.tables[0], 4) == ["청구항 4 [구성 4-1]"]
