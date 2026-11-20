"""F3 도구 등록 테스트. 진짜 DB 저장소·임베딩은 만들지 않는다 (만드는 함수를 가짜로 바꿈)."""

import pytest

from patent_ai.core.agents.tools import ToolRegistry, ToolResult
from patent_ai.core.agents.tools_f3 import RunF3Input, register_f3_tools
from patent_ai.core.f3_claim_compare import run as f3_run
from patent_ai.core.f3_claim_compare.result import F3Result
from patent_ai.core.schemas.common import StatusValue
from tests.core.f3 import scenario


@pytest.fixture
def registry(monkeypatch) -> ToolRegistry:
    # 도구는 검색기·저장소를 입력으로 받지 않고 안에서 만든다. 테스트는 메모리 것으로 바꾼다
    monkeypatch.setattr(
        f3_run, "make_search_resources", lambda config, ctx: (scenario.searcher(), scenario.REPO)
    )
    reg = ToolRegistry()
    register_f3_tools(reg)
    return reg


def _input() -> dict:
    return {
        "oa_result": scenario.oa_result().model_dump(),
        "case_materials": scenario.MATERIALS.model_dump(),
        "config": scenario.config().model_dump(),
    }


def test_run_f3_도구가_code_tool로_등록된다(registry):
    tool = registry.get("run_f3")
    assert tool.kind == "code_tool"
    assert tool.input_schema is RunF3Input and tool.output_schema is F3Result


def test_dict_입력으로_돌리면_status가_있는_결과가_나온다(registry):
    ctx, _ = scenario.context()
    out = registry.get("run_f3").run(_input(), ctx)
    assert isinstance(out, ToolResult) and isinstance(out.result, F3Result)
    assert out.status == out.result.status
    assert out.status.value == StatusValue.NOT_FOUND_IN_SCOPE
    assert [t.unit_id for t in out.result.comparisons] == ["oa_1:29-2:c1"]


def test_같은_이름을_두_번_등록하면_오류(registry):
    with pytest.raises(ValueError, match="이미 등록된 도구"):
        register_f3_tools(registry)


def test_ctx_없이_부르면_ValueError(registry):
    with pytest.raises(ValueError, match="ctx"):
        registry.get("run_f3").run(_input())
