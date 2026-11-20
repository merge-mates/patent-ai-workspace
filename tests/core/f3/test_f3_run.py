"""run_f3 한 바퀴 테스트: 나누기 -> 판단 단위 -> 대비 + 명확성 -> F3Result. 진짜 호출·DB 없음."""

import json
import logging

import pytest

from patent_ai.core.f3_claim_compare.result import F3Result
from patent_ai.core.f3_claim_compare.run import run_f3
from patent_ai.core.llm.errors import ModelOutputInvalid
from patent_ai.core.llm.transport import TransportResponse
from patent_ai.core.schemas.common import Flag, StatusValue, UnverifiedReason
from tests.core.f3 import scenario
from tests.core.f3.fakes import OK, bad, citation, oa, rejection


def _run(oa=None, config=None, answers=None):
    ctx, transport = scenario.context(answers)
    result = run_f3(
        oa or scenario.oa_result(),
        scenario.MATERIALS,
        config or scenario.config(),
        ctx=ctx,
        searcher=scenario.searcher(),
        repo=scenario.REPO,
    )
    return result, transport


def test_한_바퀴를_돌면_판단_단위와_대비표와_명확성_검토가_한_결과에_담긴다():
    result, transport = _run()
    assert isinstance(result, F3Result) and result.oa_id == "oa_1"
    assert [u.unit_id for u in result.units] == ["oa_1:29-2:c1", "oa_1:42-4-2:c2"]
    (table,) = result.comparisons
    assert table.unit_id == "oa_1:29-2:c1" and {r.claim for r in table.rows} == {1, 2}
    (review,) = result.clarity_reviews
    assert (review.unit_id, review.claim, review.term) == ("oa_1:42-4-2:c2", 2, scenario.MODULE)
    assert len(result.search_log) == 3  # 구성요소 3개 × D1
    # 단계 순서: 청구항 나누기 → 대비 → 명확성
    assert [c["step"] for c in transport.calls] == [
        "f3.split_elements",
        "f3.split_elements",
        "f3.compare",
        "f3.compare",
        "f3.clarity",
    ]


def test_결과_status는_안쪽_status_중_가장_나쁜_값이다():
    result, _ = _run()
    # 대비표에 못 찾은 줄(조회 범위 내 없음), 명확성에 정의를 못 고른 검토가 있다
    assert result.comparisons[0].status.value == StatusValue.NOT_FOUND_IN_SCOPE
    assert result.clarity_reviews[0].status.value == StatusValue.NOT_FOUND_IN_SCOPE
    assert result.status.value == StatusValue.NOT_FOUND_IN_SCOPE
    assert result.status.searched_scope


def test_한국_미국_밖_문헌은_지원_안_함으로_결과에_남는다():
    result, _ = _run()
    table = result.comparisons[0]
    d2 = next(c for c in table.citations if c.label == "D2")
    assert d2.compared is False
    assert d2.skipped_reason == "지원 안 하는 나라 (JP) · 직접 확인"
    assert Flag.NEEDS_HUMAN_REVIEW in table.flags
    assert {r.citation for r in table.rows} == {"D1"}


def test_지원_안_하는_거절이유는_단위를_만들지_않고_경고한다(caplog):
    with caplog.at_level(logging.WARNING):
        result, _ = _run()
    assert all(u.rejection != 3 for u in result.units)
    assert any("거절이유 3" in r.getMessage() for r in caplog.records)


def test_대상_청구항이_인용하는_앞_청구항도_나눈다():
    # 거절이유가 청구항 2만 짚어도 청구항 1(인용되는 항)을 나눠야 묶음과 함께 읽을 항을 안다
    answers = scenario.responses()
    answers["f3.split_elements"] = list(reversed(answers["f3.split_elements"]))  # 2 먼저, 그다음 1
    answers["f3.compare"] = answers["f3.compare"][1:]
    result, transport = _run(scenario.oa_result(claims=(2,)), answers=answers)
    assert [c["step"] for c in transport.calls].count("f3.split_elements") == 2
    assert result.units[0].unit_id == "oa_1:29-2:c2" and result.units[0].claims == [2]
    assert result.clarity_reviews[0].claim == 2


def test_단계가_실패하면_삼키지_않고_예외로_올린다():
    answers = scenario.responses()
    answers["f3.compare"] = [TransportResponse("대비 결과입니다", 100, 50)] * 2
    with pytest.raises(ModelOutputInvalid):
        _run(answers=answers)


def test_청구항_판이_확인되지_않으면_결과_전체가_input_unverified():
    config = scenario.config(claims_status=bad(UnverifiedReason.EDITION_UNKNOWN))
    result, _ = _run(config=config)
    assert result.status.reason == UnverifiedReason.INPUT_UNVERIFIED
    assert all(u.status.reason == UnverifiedReason.INPUT_UNVERIFIED for u in result.units)
    assert result.comparisons[0].status.reason == UnverifiedReason.INPUT_UNVERIFIED
    assert result.clarity_reviews[0].status.reason == UnverifiedReason.INPUT_UNVERIFIED


def test_청구항_글자가_없는_대상_청구항은_보류로_남긴다(caplog):
    config = scenario.config()
    inputs = config.inputs.model_copy(update={"claims_at_oa": {1: scenario.CLAIMS[1]}})
    answers = scenario.responses()
    answers["f3.split_elements"] = answers["f3.split_elements"][:1]
    answers["f3.compare"] = answers["f3.compare"][:1]
    answers["f3.clarity"] = []
    with caplog.at_level(logging.WARNING):
        result, _ = _run(config=config.model_copy(update={"inputs": inputs}), answers=answers)
    assert "f3_split:oa_1:claim2" in [h.task for h in result.held_tasks]
    assert result.status.value == StatusValue.UNVERIFIED


def test_검색기만_주고_저장소를_안_주면_멈춘다():
    ctx, _ = scenario.context()
    with pytest.raises(ValueError, match="repo"):
        run_f3(
            scenario.oa_result(),
            scenario.MATERIALS,
            scenario.config(),
            ctx=ctx,
            searcher=scenario.searcher(),
        )


# ---- B4·B8 리뷰 고침: 낮춘 판단 단위가 대비 단계에 들어간다 ----
def _novelty_run(claims_status):
    """신규성 한 건: 구성요소 1 개시됨, 2는 근거가 있는 차이 후보 (못 찾음이 아님)."""
    result = oa([rejection(1, "29-1-1", [1], [citation("D1", scenario.D1)])])
    answers = scenario.responses()
    answers["f3.split_elements"] = answers["f3.split_elements"][:1]
    rows = [
        {
            "element_no": 1,
            "citation": "D1",
            "judgment": "disclosed",
            "evidence": [{"chunk_id": scenario.P23, "quote": "습도 센서는 흙에 꽂혀 습도를 잰다"}],
        },
        {
            "element_no": 2,
            "citation": "D1",
            "judgment": "difference_candidate",
            "evidence": [{"chunk_id": scenario.P31, "quote": "물통은 물을 담아 둔다"}],
        },
    ]
    body = json.dumps({"claim": 1, "rows": rows}, ensure_ascii=False)
    answers["f3.compare"] = [TransportResponse(body, 100, 50)]
    answers["f3.clarity"] = []
    return _run(result, scenario.config(claims_status=claims_status), answers)[0]


def test_청구항_판이_확인되지_않으면_신규성_대비표에_직접_검토_필요가_붙는다():
    confirmed = _novelty_run(OK)
    assert confirmed.comparisons[0].summary.verdict == "different"
    assert confirmed.comparisons[0].flags == []
    lowered = _novelty_run(bad(UnverifiedReason.EDITION_UNKNOWN))
    assert lowered.comparisons[0].summary.verdict == "different"  # 요약은 그대로
    assert Flag.NEEDS_HUMAN_REVIEW in lowered.comparisons[0].flags
