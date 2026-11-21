"""F3 도구 등록. tools.py의 register_f1_tools와 같은 모양이다 (지휘는 이름만 붙이면 된다).

입력은 데이터만 받는다. 검색기·조각 저장소 같은 객체는 입력에 넣지 않고 run_f3가 안에서 만든다.
"""

from pydantic import BaseModel

from patent_ai.core.agents.tools import Tool, ToolRegistry
from patent_ai.core.f3_claim_compare.inputs import F3Config
from patent_ai.core.f3_claim_compare.result import F3Result
from patent_ai.core.llm.limits import RunContext
from patent_ai.core.schemas.case_materials import CaseMaterials
from patent_ai.core.schemas.oa_result import OAResult


class RunF3Input(BaseModel):
    """ctx(실행 맥락)는 입력이 아니라 run(input, ctx)로 따로 넘긴다."""

    oa_result: OAResult
    case_materials: CaseMaterials
    config: F3Config  # yaml 설정 값 + 글자 입력(OA 당시 청구항, 최초 명세서)


def _run_f3(i: RunF3Input, ctx: RunContext | None) -> F3Result:
    from patent_ai.core.f3_claim_compare.run import run_f3

    if ctx is None:
        raise ValueError("run_f3는 실행 맥락(ctx)이 필요함")
    return run_f3(i.oa_result, i.case_materials, i.config, ctx=ctx)


def register_f3_tools(registry: ToolRegistry) -> None:
    """F3 도구를 등록한다."""
    registry.register(Tool("run_f3", "code_tool", RunF3Input, F3Result, _run_f3))
