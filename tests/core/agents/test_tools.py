"""도구 규약과 등록 테스트 (tasks-2.md m1-i2-15 task-1)."""

import pytest
from pydantic import BaseModel

from patent_ai.core.agents.tools import (
    Tool,
    ToolNotFound,
    ToolOutputInvalid,
    ToolRegistry,
    ToolResult,
    register_f1_tools,
)
from patent_ai.core.schemas.common import Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.document import PageText


class _In(BaseModel):
    n: int


class _Out(BaseModel):
    n: int
    status: Status


class _OutNoStatus(BaseModel):
    n: int


_OK = Status(value=StatusValue.CONFIRMED, checked="테스트")


def _tool(name="t", fn=None, output=_Out, kind="code_tool") -> Tool:
    return Tool(
        name=name,
        kind=kind,
        input_schema=_In,
        output_schema=output,
        fn=fn or (lambda i, ctx: _Out(n=i.n + 1, status=_OK)),
    )


def test_등록하고_이름으로_꺼내_돌린다():
    reg = ToolRegistry()
    reg.register(_tool())
    out = reg.get("t").run({"n": 1})
    assert isinstance(out, ToolResult)
    assert out.result.n == 2
    assert out.status == _OK
    assert out.evidence == []


def test_kind별_목록():
    reg = ToolRegistry()
    reg.register(_tool("a", kind="code_tool"))
    reg.register(_tool("b", kind="fixed_stage"))
    assert [t.name for t in reg.list()] == ["a", "b"]
    assert [t.name for t in reg.list(kind="fixed_stage")] == ["b"]
    assert reg.list(kind="subagent") == []


def test_없는_이름은_ToolNotFound():
    with pytest.raises(ToolNotFound):
        ToolRegistry().get("없음")


def test_같은_이름_두_번_등록은_거부():
    reg = ToolRegistry()
    reg.register(_tool())
    with pytest.raises(ValueError):
        reg.register(_tool())


def test_출력이_output_schema에_안_맞으면_거부():
    bad = _tool(fn=lambda i, ctx: _OutNoStatus(n=1))
    with pytest.raises(ToolOutputInvalid):
        bad.run({"n": 1})


def test_status_없는_결과는_거부():
    t = _tool(output=_OutNoStatus, fn=lambda i, ctx: _OutNoStatus(n=1))
    with pytest.raises(ToolOutputInvalid):
        t.run({"n": 1})


def test_결과가_ResultBase면_그_status와_evidence를_그대로():
    from patent_ai.core.schemas.common import Evidence, ResultBase

    ev = Evidence(document_id="d", page=1, raw_text="글")
    res = ResultBase(status=_OK, evidence=[ev])
    t = Tool(name="r", kind="code_tool", input_schema=_In, output_schema=ResultBase,
             fn=lambda i, ctx: res)
    out = t.run({"n": 1})
    assert out.status == _OK
    assert out.evidence == [ev]


def test_F1_도구_세_개가_맞는_kind로_등록된다():
    reg = ToolRegistry()
    register_f1_tools(reg)
    assert reg.get("extract_pages").kind == "code_tool"
    assert reg.get("read_oa").kind == "code_tool"
    assert reg.get("cut_to_oa").kind == "fixed_stage"
    assert reg.get("extract_pages").output_schema is PageText


def test_cut_to_oa는_입력을_그대로_넘기고_경고를_남긴다(caplog):
    reg = ToolRegistry()
    register_f1_tools(reg)
    with caplog.at_level("WARNING"):
        out = reg.get("cut_to_oa").run({"materials": ["a", "b"]})
    assert out.result.materials == ["a", "b"]
    assert out.status.value == StatusValue.UNVERIFIED
    assert out.status.reason == UnverifiedReason.NOT_EXTRACTED
    assert "자르기 몸통은 #54" in caplog.text
