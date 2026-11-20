"""F4 도구 등록. 지휘 쪽은 register_f4_tools(registry) 한 줄과 순서 이름(run_f4)만 붙이면 된다.

종류는 code_tool: 지금 지휘가 골라 부를 수 있는 종류가 code_tool뿐이고(read_oa와 같음),
fixed_stage는 ADR 0003 목록(초안 검사·자르기 등)에만 쓴다.
"""

from patent_ai.core.agents.tools import Tool, ToolRegistry
from patent_ai.core.f4_response_draft.inputs import F4Input
from patent_ai.core.f4_response_draft.result import F4Output
from patent_ai.core.llm.limits import RunContext


def _run_f4(i: F4Input, ctx: RunContext | None) -> F4Output:
    from patent_ai.core.f4_response_draft.run import run_f4

    if ctx is None:
        raise ValueError("run_f4는 실행 맥락(ctx)이 필요함")
    return run_f4(i, ctx=ctx)


def register_f4_tools(registry: ToolRegistry) -> None:
    """F4 도구를 등록한다: run_f4(F4Input) -> F4Output."""
    registry.register(Tool("run_f4", "code_tool", F4Input, F4Output, _run_f4))
