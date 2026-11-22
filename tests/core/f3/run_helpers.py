"""F3 run_f3 테스트 공용: 지어낸 사건 하나를 돌린다."""

from patent_ai.core.f3_claim_compare.run import run_f3
from tests.core.f3 import scenario


def run_scenario(oa=None, config=None, answers=None, ctx=None, transport=None):
    if ctx is None:
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
