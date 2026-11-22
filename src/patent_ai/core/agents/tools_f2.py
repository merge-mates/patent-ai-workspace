"""F2 도구 등록. tools_f3.py와 같은 모양이다 (지휘는 이름 run_f2만 붙이면 된다).

입력은 데이터만 받는다. 법령 조각 저장소는 run_f2가 안에서 만든다 (make_law_repo).
"""

from patent_ai.core.agents.tools import Tool, ToolRegistry
from patent_ai.core.f2_legal_research.run import F2Input, F2Result
from patent_ai.core.llm.limits import RunContext


def _run_f2(i: F2Input, ctx: RunContext | None) -> F2Result:
    from patent_ai.core.f2_legal_research.run import run_f2

    # 걷는 뼈대는 모델을 부르지 않아 ctx를 쓰지 않는다 (근거 검토가 붙는 #29에서 씀)
    return run_f2(i)


def register_f2_tools(registry: ToolRegistry) -> None:
    """F2 도구를 등록한다: run_f2(F2Input) -> F2Result."""
    registry.register(Tool("run_f2", "code_tool", F2Input, F2Result, _run_f2))
