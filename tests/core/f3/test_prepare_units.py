"""prepare_units: F3 앞 고정 단계로 꺼낸 판단 단위 나누기 (이슈 #309 task-2). 진짜 호출·DB 없음."""

import logging

import pytest

from patent_ai.core.f3_claim_compare.inputs import F3Config, F3Inputs
from patent_ai.core.f3_claim_compare.run import PreparedUnits, prepare_units, run_f3
from patent_ai.core.llm.errors import ModelOutputInvalid
from patent_ai.core.llm.transport import TransportResponse
from patent_ai.core.schemas.common import StatusValue, UnverifiedReason
from tests.core.f3 import scenario
from tests.core.f3.fakes import OK, bad, oa, rejection


def _splits(transport) -> int:
    return sum(1 for c in transport.calls if c["step"] == "f3.split_elements")


def test_prepare_units는_청구항을_나눠_판단_단위를_만든다():
    ctx, transport = scenario.context()
    prepared = prepare_units(scenario.oa_result(), scenario.config(), ctx=ctx)
    assert isinstance(prepared, PreparedUnits)
    assert sorted(prepared.splits) == [1, 2]
    assert [u.unit_id for u in prepared.units] == ["oa_1:29-2:c1", "oa_1:42-4-2:c2"]
    assert prepared.held_tasks == []
    assert _splits(transport) == 2 and len(transport.calls) == 2  # 나누기만 부른다
    assert prepared.status.value == StatusValue.CONFIRMED  # units status 중 가장 나쁜 값


def test_prepared를_주면_나누기를_다시_부르지_않고_안_주고_돈_결과와_같다():
    ctx, transport = scenario.context()
    prepared = prepare_units(scenario.oa_result(), scenario.config(), ctx=ctx)
    kwargs = {"searcher": scenario.searcher(), "repo": scenario.REPO}
    with_prepared = run_f3(
        scenario.oa_result(),
        scenario.MATERIALS,
        scenario.config(),
        ctx=ctx,
        prepared=prepared,
        **kwargs,
    )
    assert _splits(transport) == 2  # prepare_units에서 두 번, run_f3에서 더 안 부름

    ctx2, transport2 = scenario.context()
    without = run_f3(
        scenario.oa_result(), scenario.MATERIALS, scenario.config(), ctx=ctx2, **kwargs
    )
    assert _splits(transport2) == 2  # 옛 호출도 그대로 돈다 (안에서 prepare_units)
    assert with_prepared == without
    # 모델 호출 수·순서도 같다
    assert [c["step"] for c in transport.calls] == [c["step"] for c in transport2.calls]


def test_청구항_글자가_없으면_보류_줄이_F3_결과_held_tasks에_그대로_남는다():
    claims = {1: scenario.CLAIMS[1]}  # 청구항 2 글자 없음 (거절이유 2가 청구항 2를 짚음)
    config = F3Config(
        settings=scenario.config().settings,
        inputs=F3Inputs(
            claims_at_oa=claims, claims_status=OK, claims_document_id="d", spec=scenario.SPEC
        ),
    )
    answers = scenario.responses()
    answers["f3.split_elements"] = answers["f3.split_elements"][:1]
    ctx, _ = scenario.context(answers)
    prepared = prepare_units(scenario.oa_result(), config, ctx=ctx)
    assert [h.task for h in prepared.held_tasks] == ["f3_split:oa_1:claim2"]

    result = run_f3(
        scenario.oa_result(),
        scenario.MATERIALS,
        config,
        ctx=ctx,
        searcher=scenario.searcher(),
        repo=scenario.REPO,
        prepared=prepared,
    )
    assert "f3_split:oa_1:claim2" in [h.task for h in result.held_tasks]


def test_청구항_판이_확인되지_않았으면_단위를_input_unverified로_낮춘다():
    ctx, _ = scenario.context()
    config = scenario.config(claims_status=bad(UnverifiedReason.INPUT_UNVERIFIED))
    prepared = prepare_units(scenario.oa_result(), config, ctx=ctx)
    assert prepared.units and all(
        u.status.reason == UnverifiedReason.INPUT_UNVERIFIED for u in prepared.units
    )
    assert prepared.status.value == StatusValue.UNVERIFIED


def test_단위가_0개면_경고를_남기고_status는_확인되지_않음이다(caplog):
    only_unsupported = oa([rejection(1, "45", [1])])  # 지원 안 하는 조문뿐 -> 단위 없음
    ctx, _ = scenario.context({})
    with caplog.at_level(logging.WARNING):
        prepared = prepare_units(only_unsupported, scenario.config(), ctx=ctx)
    assert prepared.units == []
    assert prepared.status.value == StatusValue.UNVERIFIED
    assert prepared.status.reason == UnverifiedReason.NOT_EXTRACTED
    assert any("판단 단위" in r.getMessage() for r in caplog.records)


def test_나누기_모델_호출이_실패하면_run_f3와_같은_예외로_멈춘다():
    broken = TransportResponse("JSON 아님", 10, 10)
    answers = scenario.responses()
    # #322 뒤: 청구항 하나만 실패하면 그 청구항만 보류. 모델을 부른 청구항(2개)이 모두
    # 실패해야(다시 부른 답까지 2 × 2) run_f3와 같은 예외로 멈춘다
    answers["f3.split_elements"] = [broken] * 4
    ctx, _ = scenario.context(answers)
    with pytest.raises(ModelOutputInvalid):
        prepare_units(scenario.oa_result(), scenario.config(), ctx=ctx)
