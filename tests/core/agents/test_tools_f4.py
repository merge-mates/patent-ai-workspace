"""F4 도구 등록 테스트. 기대값은 구현 계획 C4와 core/agents/tools.py의 도구 규약."""

import json
from pathlib import Path

import pytest

from patent_ai.core.agents.tools import ToolRegistry, ToolResult
from patent_ai.core.agents.tools_f4 import register_f4_tools
from patent_ai.core.f4_response_draft.inputs import F4Input
from patent_ai.core.f4_response_draft.result import F4Output
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.common import StatusValue

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "f4"


def _json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text("utf-8"))


def _ctx() -> RunContext:
    def answers(*names):
        return [
            TransportResponse(json.dumps(_json(f"llm/{n}.json"), ensure_ascii=False), 100, 50)
            for n in names
        ]

    transport = FakeTransport(
        {
            "f4.direction": answers("direction_inventive", "direction_clarity"),
            "f4.opinion": answers("opinion_inventive", "opinion_clarity"),
            "f4.amendment": answers("amendment_inventive", "amendment_clarity"),
        }
    )
    return RunContext(
        run_id="r_1", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )


def test_run_f4_도구가_등록되고_입출력_스키마가_맞다():
    reg = ToolRegistry()
    register_f4_tools(reg)
    tool = reg.get("run_f4")
    assert (tool.input_schema, tool.output_schema) == (F4Input, F4Output)
    assert [t.name for t in reg.list("code_tool")] == ["run_f4"]  # 지휘가 골라 부를 수 있는 종류


def test_dict_입력으로_돌리면_status가_있는_결과가_나온다():
    reg = ToolRegistry()
    register_f4_tools(reg)
    out = reg.get("run_f4").run(_json("case_basic.json"), _ctx())
    assert isinstance(out, ToolResult) and isinstance(out.result, F4Output)
    assert out.status == out.result.status
    assert out.status.value == StatusValue.UNVERIFIED
    assert len(out.result.directions) == 2 and out.result.drafts is not None


def test_입력_객체로_돌려도_같다():
    reg = ToolRegistry()
    register_f4_tools(reg)
    inp = F4Input.model_validate(_json("case_basic.json"))
    out = reg.get("run_f4").run(inp, _ctx())
    assert out.result.oa_id == "oa_1"


def test_실행_맥락_없이_부르면_멈춘다():
    reg = ToolRegistry()
    register_f4_tools(reg)
    with pytest.raises(ValueError, match="ctx"):
        reg.get("run_f4").run(_json("case_basic.json"))


def test_같은_이름을_두_번_등록하면_오류():
    reg = ToolRegistry()
    register_f4_tools(reg)
    with pytest.raises(ValueError, match="run_f4"):
        register_f4_tools(reg)
