"""대비 방식 고르기(impl, B8) 테스트: 이름 -> 구현 등록·조회, run_f3는 그 인터페이스만 부른다."""

import pytest

from patent_ai.core.f3_claim_compare import strategies
from patent_ai.core.f3_claim_compare.compare import CompareOutput
from patent_ai.core.f3_claim_compare.config import load_f3_settings
from patent_ai.core.f3_claim_compare.run import run_f3
from patent_ai.core.f3_claim_compare.strategies import (
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
    seen: list[list[str]] = []

    @register_strategy("fake_impl")
    def fake(units, oa, splits, config, *, ctx, resources):
        seen.append([u.unit_id for u in units])
        assert sorted(splits) == [1, 2]  # 나눈 청구항은 공통 단계가 만들어 넘긴다
        return CompareOutput()

    config = scenario.config()
    settings = config.settings.model_copy(update={"impl": "fake_impl"})
    ctx, transport = scenario.context()
    result = run_f3(
        scenario.oa_result(),
        scenario.MATERIALS,
        config.model_copy(update={"settings": settings}),
        ctx=ctx,
        searcher=scenario.searcher(),
        repo=scenario.REPO,
    )
    # 방식은 판단 단위를 받아 진보성·신규성 대비만 맡는다
    assert seen == [["oa_1:29-2:c1", "oa_1:42-4-2:c2"]]
    assert result.comparisons == []
    # 청구항 나누기·판단 단위·명확성 검토는 방식과 상관없이 그대로 나온다
    assert [u.unit_id for u in result.units] == ["oa_1:29-2:c1", "oa_1:42-4-2:c2"]
    assert [r.unit_id for r in result.clarity_reviews] == ["oa_1:42-4-2:c2"]
    steps = [c["step"] for c in transport.calls]
    assert steps == ["f3.split_elements", "f3.split_elements", "f3.clarity"]


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
