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
from patent_ai.core.schemas.comparison import NoveltyVerdict, ParagraphSource
from patent_ai.retrieval.repository import InMemoryChunkRepository
from tests.core.f3.fakes import OK, bad, citation, claim_row, oa, paragraph, rejection, split

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
    # 심사관만 짚는 조각: 어느 구성요소 글자·방향과도 겹치지 않는다
    paragraph(D1, 50, "다리가 셋 달려 있다", [-1.0, -1.0]),
]
P23, P31, P40, P50 = (c.chunk_id for c in CHUNKS)
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
            # 가짜 응답 개수는 한 번만 찾기 기준 (한 번 더 찾기는 test_f3_second_search.py가 본다)
            "second_search": False,
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
    scope = "D1 조각 4개 중 hybrid 상위 1 (cite-idx-v2)"
    assert (
        f"청구항 1 [구성 1-2] {TANK} (조회 범위 내 없음: {scope}, 없다는 판단 아님)"
        " (청구항 3에서 인용)"
    ) in differences
    assert not any("청구항 5에서 인용" in d for d in differences)
    assert f"청구항 3 [구성 3-1] {LID} (불명)" in differences


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
        [claim_row(3, 1, ["D1"], {"D1": ["[0050]"]})],
    )
    answer = _answer(3, (1, "unclear"), (2, "unclear"), (3, "unclear"))
    out, calls, searches, _ = _run(result, [answer], config=_config(use_examiner=False))
    # 심사관 위치의 조각은 어느 구성요소 검색에도 안 걸린다: 프롬프트에 글자가 없어야 한다
    assert "다리가 셋" not in calls[0]["prompt"] and all("0050" not in q for q in searches)
    # 대조: 심사관 위치를 켜면 같은 조각이 후보로 들어간다
    _, calls_on, _, _ = _run(result, [answer], config=_config(use_examiner=True))
    assert "다리가 셋" in calls_on[0]["prompt"]
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


# ---- 리뷰 고침 1회차: 문헌별로 따지기, 가지 여럿, 나누기 실패 ----
D2 = "KR20990000002A"


def _raw(claim: int, rows: list[tuple[int, str]]) -> TransportResponse:
    """(구성요소 번호, 인용문헌 라벨) 줄마다 불명으로 답한다."""
    made = [
        {"element_no": n, "citation": label, "judgment": "unclear", "evidence": []}
        for n, label in rows
    ]
    return TransportResponse(json.dumps({"claim": claim, "rows": made}, ensure_ascii=False), 1, 1)


def _two_docs():
    chunks = [
        paragraph(D1, 23, "습도 센서는 흙에 꽂혀 습도를 잰다", [1.0, 0.0]),
        paragraph(D2, 7, "센서와 물통이 있다", [0.0, 1.0]),
    ]
    return InMemoryChunkRepository({"cite": chunks})


def _run_two_docs(result, responses):
    repo = _two_docs()
    inner = make_searcher(load_f3_settings(), repo, lambda q: [1.0, 0.0])
    transport = FakeTransport({STEP: responses})
    ctx = RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    units, _ = build_units(result, SPLITS)
    out = compare_unit(units[0], result, SPLITS, _config(), ctx=ctx, searcher=inner, repo=repo)
    return out, units


def test_신규성은_문헌마다_따져_부모가_그_문헌과_대비되지_않았으면_부모_구성요소를_넣는다():
    # 청구항 1은 D1만, 청구항 3은 D2만: D2 표에서 청구항 1은 D2와 대비되지 않았다
    result = oa(
        [rejection(1, "29-1-1", [1, 3], [citation("D1", D1), citation("D2", D2)])],
        [claim_row(1, 1, ["D1"]), claim_row(3, 1, ["D2"])],
    )
    responses = [_raw(1, [(1, "D1"), (2, "D1")]), _raw(3, [(1, "D2"), (2, "D2"), (3, "D2")])]
    out, _ = _run_two_docs(result, responses)
    d1_table, d2_table = out.tables
    assert _locations(d1_table, 1) == ["청구항 1 [구성 1-1]", "청구항 1 [구성 1-2]"]
    assert _locations(d2_table, 3) == [
        "청구항 1 [구성 1-1]",
        "청구항 1 [구성 1-2]",
        "청구항 3 [구성 3-1]",
    ]
    # 가지가 아닌 보통 종속항 표에는 가지 보류 문구가 붙지 않는다
    assert _BRANCH_NOTE not in d2_table.summary.reason


def test_진보성은_종속항에만_붙은_문헌이_있으면_부모_구성요소를_넣는다():
    # 청구항 1은 D1, 청구항 3은 D1·D2: 부모가 D2와는 대비되지 않았다
    result = oa(
        [rejection(1, "29-2", [1, 3], [citation("D1", D1), citation("D2", D2)])],
        [claim_row(1, 1, ["D1"]), claim_row(3, 1, ["D1", "D2"])],
    )
    both = [(n, label) for n in (1, 2, 3) for label in ("D1", "D2")]
    out, _ = _run_two_docs(result, [_raw(1, [(1, "D1"), (2, "D1")]), _raw(3, both)])
    (table,) = out.tables
    assert list(dict.fromkeys(_locations(table, 3)))[:2] == [
        "청구항 1 [구성 1-1]",
        "청구항 1 [구성 1-2]",
    ]
    assert {
        r.citation for r in table.rows if r.claim == 3 and "청구항 1" in r.element_location
    } == {
        "D1",
        "D2",
    }


def test_인용_가지가_여럿이면_부모_구성요소를_넣지_않고_경고한다(caplog):
    splits = {
        1: split(1, [SENSOR, TANK]),
        2: split(2, [LID], [1]),
        3: split(3, [BASE], [1]),
        4: split(4, [HANDLE], [2, 3]),  # 제2항 또는 제3항에 있어서
    }
    result = oa([rejection(1, "29-2", [4], [citation("D1", D1)])])
    with caplog.at_level(logging.WARNING):
        out, _, _, units = _run(result, [_answer(4, (1, "unclear"))], splits=splits)
    assert _locations(out.tables[0], 4) == ["청구항 4 [구성 4-1]"]
    assert Flag.NEEDS_HUMAN_REVIEW in out.tables[0].flags
    assert any("인용 가지가 여럿" in r.getMessage() for r in caplog.records)


def _empty_parent(**update):
    return split(1, [], []).model_copy(update=update)


def test_부모를_나누지_못했으면_경고하고_표를_input_unverified로_한다(caplog):
    # 청구항 1의 나누기 결과가 구성요소 0개 + 확인되지 않음
    splits = {1: _empty_parent(status=bad()), 3: SPLITS[3]}
    result = oa([rejection(1, "29-1-1", [3], [citation("D1", D1)])])
    with caplog.at_level(logging.WARNING):
        out, _, _, _ = _run(result, [_answer(3, (1, "unclear"))], splits=splits)
    (table,) = out.tables
    assert _locations(table, 3) == ["청구항 3 [구성 3-1]"]
    assert table.status.value == StatusValue.UNVERIFIED
    assert table.status.reason == UnverifiedReason.INPUT_UNVERIFIED
    assert Flag.NEEDS_HUMAN_REVIEW in table.flags
    assert any("부모" in r.getMessage() and "청구항 1" in r.getMessage() for r in caplog.records)


def _branch_splits():
    return {
        1: split(1, [SENSOR, TANK]),
        2: split(2, [LID], [1]),
        3: split(3, [BASE], [1]),
        4: split(4, [HANDLE], [2, 3]),  # 제2항 또는 제3항에 있어서
    }


_BRANCH_NOTE = "부모 청구항 구성요소를 대비하지 않음(인용 가지 여럿), 판단 아님"


def test_인용_가지가_여럿이고_부모를_못_빌리면_확인됨으로_나가지_않고_보류한다(caplog):
    result = oa([rejection(1, "29-1-1", [4], [citation("D1", D1)])])
    answer = _answer(4, (1, "disclosed", (P31, FULL31)))
    with caplog.at_level(logging.WARNING):
        out, _, _, _ = _run(result, [answer], splits=_branch_splits())
    (table,) = out.tables
    # 요약이 "차이 없음"이어도 표 전체는 확인됨이 아니다 (이 전제가 이 테스트의 핵심)
    assert table.summary.verdict == NoveltyVerdict.NO_DIFFERENCE
    assert _BRANCH_NOTE in table.summary.reason
    assert any("인용 가지가 여럿" in r.getMessage() for r in caplog.records)
    assert _locations(table, 4) == ["청구항 4 [구성 4-1]"]
    (row,) = table.rows
    assert row.status.value == StatusValue.UNVERIFIED
    assert row.status.reason == UnverifiedReason.INPUT_UNVERIFIED
    assert table.status.value == StatusValue.UNVERIFIED
    assert [h.task for h in out.held_tasks] == [f"f3_compare:{table.unit_id}:claim4:branch"]
    assert out.held_tasks[0].waiting_for == "인용 가지마다 대비 (직접 검토 필요)"


def test_인용_가지가_여럿이어도_부모가_이미_대비됐으면_보류도_경고도_없다(caplog):
    result = oa([rejection(1, "29-2", [1, 2, 3, 4], [citation("D1", D1)])])
    answers = [
        _answer(1, (1, "unclear"), (2, "unclear")),
        _answer(2, (1, "unclear")),
        _answer(3, (1, "unclear")),
        _answer(4, (1, "unclear")),
    ]
    with caplog.at_level(logging.WARNING):
        out, _, _, _ = _run(result, answers, splits=_branch_splits())
    assert out.held_tasks == []
    assert not any("인용 가지가 여럿" in r.getMessage() for r in caplog.records)
    assert out.tables[0].status.reason != UnverifiedReason.INPUT_UNVERIFIED
