"""도구 규약과 등록. 지휘 에이전트가 부르는 도구는 모두 같은 모양(Tool)으로 등록한다.

종류(kind): code_tool(지휘가 골라 부르는 코드 도구), fixed_stage(그래프 간선으로
늘 지나는 단계), subagent. 기준은 ADR 0003 "에이전트가 정하는 것과 코드로 고정하는 것".
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from patent_ai.core.llm.limits import RunContext
from patent_ai.core.schemas.common import (
    Evidence,
    ResultBase,
    Status,
    StatusValue,
    UnverifiedReason,
)
from patent_ai.core.schemas.document import PageText
from patent_ai.core.schemas.oa_result import OAResult

logger = logging.getLogger(__name__)

ToolKind = Literal["code_tool", "fixed_stage", "subagent"]


class ToolNotFound(KeyError):
    """등록되지 않은 도구 이름."""


class ToolOutputInvalid(Exception):
    """도구 출력이 output_schema에 안 맞거나 status가 없다."""


class ToolResult(BaseModel):
    """도구 실행 결과 공통 껍데기. result는 output_schema 객체."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    result: Any
    status: Status
    evidence: list[Evidence]


@dataclass(frozen=True)
class Tool:
    """도구 하나. fn(입력 객체, 실행 맥락) -> output_schema 객체."""

    name: str
    kind: ToolKind
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    fn: Callable[[Any, RunContext | None], Any]

    def run(self, input: dict | BaseModel, ctx: RunContext | None = None) -> ToolResult:
        # 입력을 input_schema로 검사한다 (dict도 받는다)
        data = self.input_schema.model_validate(
            input.model_dump() if isinstance(input, BaseModel) else input
        )
        out = self.fn(data, ctx)
        # 출력이 약속한 스키마가 아니면 거부
        if not isinstance(out, self.output_schema):
            raise ToolOutputInvalid(f"{self.name}: 출력이 {self.output_schema.__name__}가 아님")
        # status 없는 결과는 거부. ResultBase면 그 status·evidence를 그대로 쓴다
        status = getattr(out, "status", None)
        if not isinstance(status, Status):
            raise ToolOutputInvalid(f"{self.name}: 출력에 status가 없음")
        evidence = list(out.evidence) if isinstance(out, ResultBase) else []
        return ToolResult(result=out, status=status, evidence=evidence)


@dataclass
class ToolRegistry:
    _tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"이미 등록된 도구: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolNotFound(name)
        return self._tools[name]

    def list(self, kind: ToolKind | None = None) -> list[Tool]:
        return [t for t in self._tools.values() if kind is None or t.kind == kind]


# ---- F1 도구 ----


class ExtractPagesInput(BaseModel):
    pdf_path: Path
    document_id: str


class ReadOAInput(BaseModel):
    """ctx(실행 맥락)는 입력이 아니라 run(input, ctx)로 따로 넘긴다."""

    pages: PageText
    document_id: str
    oa_id: str
    run_id: str


class CutToOAInput(BaseModel):
    materials: list[str]  # 사건 자료 (#54 전까지 문자열 목록)


class CutToOAOutput(BaseModel):
    materials: list[str]
    status: Status


def _extract_pages(i: ExtractPagesInput, ctx: RunContext | None) -> PageText:
    from patent_ai.core.f1_oa_reader.pages import extract_pages

    return extract_pages(i.pdf_path, i.document_id)


def _read_oa(i: ReadOAInput, ctx: RunContext | None) -> OAResult:
    from patent_ai.core.f1_oa_reader.read_oa import read_oa

    if ctx is None:
        raise ValueError("read_oa는 실행 맥락(ctx)이 필요함")
    return read_oa(i.pages, i.document_id, i.oa_id, i.run_id, ctx=ctx)


def _cut_to_oa(i: CutToOAInput, ctx: RunContext | None) -> CutToOAOutput:
    # 가짜 몸통: 자료를 그대로 넘기고, 진짜 자르기가 아니라서 확인되지 않음으로 표시
    logger.warning("자르기 몸통은 #54")
    # 자료가 하나도 없으면 #54에서 진짜 자르기가 들어와도 남도록 따로 경고
    if not i.materials:
        logger.warning("cut_to_oa: 사건 자료가 비어 있음")
    return CutToOAOutput(
        materials=i.materials,
        status=Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED),
    )


def register_f1_tools(registry: ToolRegistry) -> None:
    """F1 도구 셋을 등록한다."""
    registry.register(
        Tool("extract_pages", "code_tool", ExtractPagesInput, PageText, _extract_pages)
    )
    registry.register(Tool("read_oa", "code_tool", ReadOAInput, OAResult, _read_oa))
    registry.register(Tool("cut_to_oa", "fixed_stage", CutToOAInput, CutToOAOutput, _cut_to_oa))
