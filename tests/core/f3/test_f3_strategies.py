"""대비 방식 고르기(impl, B8) 테스트: 이름 -> 구현 등록·조회, run_f3는 그 인터페이스만 부른다."""

import pytest

from patent_ai.core.f3_claim_compare import strategies
from patent_ai.core.f3_claim_compare.compare import CompareOutput
from patent_ai.core.f3_claim_compare.config import load_f3_settings
from patent_ai.core.f3_claim_compare.run import run_f3
from patent_ai.core.f3_claim_compare.strategies import (
    StrategyOutput,
    get_strategy,
    register_strategy,
    split_search,
)
from patent_ai.core.llm.errors import ModelConfigError
from tests.core.f3 import scenario


@pytest.fixture(autouse=True)
def _등록표_원래대로():
    # 테스트에서 등록한 가짜 방식이 다른 테스트로 새지 않게 되돌린다
    saved = dict(strategies._REGISTRY)
    yield
    strategies._REGISTRY.clear()
    strategies._REGISTRY.update(saved)


def test_기본_설정은_split_search를_고른다():
    assert load_f3_settings().impl == "split_search"
    assert get_strategy(load_f3_settings().impl) is split_search


def test_모르는_이름은_설정_오류로_멈춘다():
    with pytest.raises(ModelConfigError, match="no_such_impl"):
        get_strategy("no_such_impl")


def test_같은_이름에_다른_구현을_등록하면_오류():
    with pytest.raises(ValueError, match="split_search"):
        register_strategy("split_search")(lambda *a, **k: None)


def test_등록한_방식을_설정_이름으로_골라_run_f3가_부른다():
    called: list[str] = []

    @register_strategy("fake_impl")
    def fake(oa, config, *, ctx, resources):
        called.append(oa.oa_id)
        return StrategyOutput(units=[], splits={}, compared=CompareOutput(), held_tasks=[])

    config = scenario.config()
    settings = config.settings.model_copy(update={"impl": "fake_impl"})
    ctx, transport = scenario.context({})
    result = run_f3(
        scenario.oa_result(),
        scenario.MATERIALS,
        config.model_copy(update={"settings": settings}),
        ctx=ctx,
        searcher=scenario.searcher(),
        repo=scenario.REPO,
    )
    assert called == ["oa_1"]
    assert transport.calls == []  # 지금 방식(나누기 → 검색 → 대비)은 돌지 않는다
    assert result.units == [] and result.comparisons == []


def test_run_f3는_설정의_impl이_없는_이름이면_멈춘다():
    config = scenario.config()
    settings = config.settings.model_copy(update={"impl": "no_such_impl"})
    ctx, _ = scenario.context({})
    with pytest.raises(ModelConfigError):
        run_f3(
            scenario.oa_result(),
            scenario.MATERIALS,
            config.model_copy(update={"settings": settings}),
            ctx=ctx,
            searcher=scenario.searcher(),
            repo=scenario.REPO,
        )
