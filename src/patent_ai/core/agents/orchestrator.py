"""지휘 그래프 뼈대와 run_case(). 서버는 run_case 하나만 부른다.

그래프: extract_pages(늘 처음) -> decide -> read_oa -> decide -> ... -> cut_to_oa -> 끝
- decide: plan=agent면 모델이 다음 code_tool을 고르고, plan=fixed_order면 설정 순서대로.
- cut_to_oa(fixed_stage)는 decide가 stop을 낼 때 그래프 간선으로 늘 지난다 (지휘가 고르지 못함).
- 도구가 실패하면 그 자리에서 끝내고 state=failed (성공으로 끝나지 않는다).
"""

import logging
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol, TypedDict

import yaml
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ValidationError

from patent_ai.core.agents.tools import ToolOutputInvalid, ToolRegistry, register_f1_tools
from patent_ai.core.f1_oa_reader.pages import PdfReadError
from patent_ai.core.llm.client import call_model
from patent_ai.core.llm.errors import ModelCallFailed, ModelCallLimitExceeded, ModelOutputInvalid
from patent_ai.core.llm.limits import RunContext
from patent_ai.core.schemas.common import StatusValue

logger = logging.getLogger(__name__)

STEP = "agents.orchestrator"
# 도구가 이 예외를 내면 실행을 failed로 끝낸다. 그 밖의 예외(버그)는 숨기지 않고 그대로 낸다
_TOOL_ERRORS = (
    ModelCallFailed,
    ModelCallLimitExceeded,
    ModelOutputInvalid,
    PdfReadError,
    ToolOutputInvalid,
    ValidationError,
)


class CaseInput(BaseModel):
    case_id: str
    oa_document: Path
    oa_document_id: str
    materials: list[str] = []  # 사건 자료 (#54에서 DocumentRef로 바뀔 수 있음)


class CaseStore(Protocol):
    """서버가 넣어 주는 사건 저장소 (core는 api를 import하지 않는다). task-3에서 쓴다."""

    def find_oa(self, application_number: str, dispatch_number: str) -> tuple[str, str] | None:
        """같은 출원번호 + 발송번호의 OA가 이미 있으면 (case_id, oa_id)."""
        ...

    def find_case(self, application_number: str) -> str | None:
        """같은 출원번호의 기존 사건이 있으면 case_id."""
        ...


class WaitingFor(StrEnum):
    """사람을 기다리는 이유."""

    APPLICATION_NUMBER = "application_number"
    DIRECTION_SELECTION = "direction_selection"


class RunOutcome(BaseModel):
    state: Literal["succeeded", "failed", "waiting_for_human"]
    results: dict[str, Any] = {}  # 도구 이름 -> 결과 객체
    waiting_for: WaitingFor | None = None
    error: dict | None = None  # {code, message} (+ oa_already_exists면 case_id, oa_id)
    searched_scope: str | None = None  # max_steps로 멈췄을 때 찾아본 범위(돈 도구 목록)
    case_id: str


class NextAction(BaseModel):
    """지휘 모델의 답: 다음에 부를 code_tool 이름 또는 "stop"."""

    next_tool: str
    reason: str


class _State(TypedDict):
    results: dict[str, Any]
    steps: int
    next_tool: str | None
    error: dict | None
    waiting_for: WaitingFor | None
    case_id: str  # 같은 출원번호의 기존 사건이 있으면 그 사건


def _error(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def run_case(
    case_input: CaseInput,
    oa_id: str,
    run_id: str,
    store: CaseStore | None,
    config_path: Path,
    *,
    ctx: RunContext,
) -> RunOutcome:
    """사건 1건을 그래프로 돌려 RunOutcome을 돌려준다. ctx는 서버가 실행마다 만든다."""
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    plan = cfg.get("plan", "agent")
    if plan not in ("agent", "fixed_order"):
        raise ValueError(f"plan은 agent 또는 fixed_order여야 함: {plan!r}")
    fixed_order: list[str] = cfg.get("fixed_order", [])
    max_steps: int = cfg.get("max_steps", 10)

    registry = ToolRegistry()
    register_f1_tools(registry)
    code_tools = {t.name for t in registry.list(kind="code_tool")}

    def call_tool(name: str, state: _State, payload: dict) -> dict:
        """도구 하나를 돌려 결과를 상태에 쌓는다. 실패하면 error를 채운다."""
        try:
            out = registry.get(name).run(payload, ctx)
        except _TOOL_ERRORS as e:
            return {"error": _error(type(e).__name__, str(e))}
        return {"results": {**state["results"], name: out.result}, "steps": state["steps"] + 1}

    # ---- 노드 ----
    def extract_pages_node(state: _State) -> dict:
        return call_tool(
            "extract_pages",
            state,
            {"pdf_path": case_input.oa_document, "document_id": case_input.oa_document_id},
        )

    def decide_node(state: _State) -> dict:
        if state["steps"] >= max_steps:
            # 못 끝낸 것을 성공으로 두지 않고, 어디까지 돌았는지 남긴다
            return {
                "error": _error(
                    "max_steps",
                    f"도구 호출 최대 {max_steps}번에 닿음. 돈 도구: {', '.join(state['results'])}",
                )
            }
        if plan == "fixed_order":
            todo = [n for n in fixed_order if n not in state["results"]]
            choice = todo[0] if todo else "stop"
        else:
            try:
                choice = _ask_model(registry, state, ctx)
            except _TOOL_ERRORS as e:
                return {"error": _error(type(e).__name__, str(e))}
        if choice == "stop":
            # 자르기 앞에 read_oa 결과가 있어야 한다
            if "read_oa" not in state["results"]:
                return {"error": _error("no_oa_result", "read_oa 없이 멈춤")}
        elif choice not in code_tools:
            # fixed_stage·없는 이름은 지휘가 고를 수 없다
            return {"error": _error("invalid_tool_choice", f"고를 수 없는 도구: {choice}")}
        return {"next_tool": choice}

    def check_oa_node(state: _State) -> dict:
        """read_oa 뒤 검사: 출원번호를 모르면 사람을 기다리고, 이미 있는 OA면 실패로 끝낸다."""
        oa = state["results"]["read_oa"]
        app, disp = oa.application_number, oa.dispatch_number
        if app.status.value != StatusValue.CONFIRMED:  # unverified·conflict
            return {"waiting_for": WaitingFor.APPLICATION_NUMBER}
        if store is None:
            return {}
        if disp.status.value == StatusValue.CONFIRMED:
            found = store.find_oa(app.value, disp.value)
            if found is not None:
                case_id, found_oa_id = found
                return {
                    "case_id": case_id,
                    "error": {
                        **_error("oa_already_exists", f"이미 있는 OA: {found_oa_id}"),
                        "case_id": case_id,
                        "oa_id": found_oa_id,
                    },
                }
        return {"case_id": store.find_case(app.value) or state["case_id"]}

    def read_oa_node(state: _State) -> dict:
        return call_tool(
            "read_oa",
            state,
            {
                "pages": state["results"]["extract_pages"],
                "document_id": case_input.oa_document_id,
                "oa_id": oa_id,
                "run_id": run_id,
            },
        )

    def cut_node(state: _State) -> dict:
        return call_tool("cut_to_oa", state, {"materials": case_input.materials})

    # ---- 간선 ----
    def stop_on_error(nxt: str) -> Callable[[_State], str]:
        return lambda s: END if s["error"] else nxt

    def after_decide(s: _State) -> str:
        if s["error"]:
            return END
        return "cut_to_oa" if s["next_tool"] == "stop" else s["next_tool"]

    g = StateGraph(_State)
    g.add_node("extract_pages", extract_pages_node)
    g.add_node("decide", decide_node)
    g.add_node("read_oa", read_oa_node)
    g.add_node("check_oa", check_oa_node)
    g.add_node("cut_to_oa", cut_node)
    g.add_edge(START, "extract_pages")
    g.add_conditional_edges("extract_pages", stop_on_error("decide"), ["decide", END])
    g.add_conditional_edges("decide", after_decide, ["extract_pages", "read_oa", "cut_to_oa", END])
    g.add_conditional_edges("read_oa", stop_on_error("check_oa"), ["check_oa", END])
    g.add_conditional_edges(
        "check_oa",
        lambda s: END if s["error"] or s["waiting_for"] else "decide",
        ["decide", END],
    )
    g.add_edge("cut_to_oa", END)

    final = g.compile().invoke(
        {
            "results": {},
            "steps": 0,
            "next_tool": None,
            "error": None,
            "waiting_for": None,
            "case_id": case_input.case_id,
        }
    )

    base = {"results": final["results"], "case_id": final["case_id"]}
    if final["error"]:
        logger.warning("run_case %s 실패: %s", run_id, final["error"])
        scope = ", ".join(final["results"]) if final["error"]["code"] == "max_steps" else None
        return RunOutcome(state="failed", error=final["error"], searched_scope=scope, **base)
    if final["waiting_for"]:
        return RunOutcome(state="waiting_for_human", waiting_for=final["waiting_for"], **base)
    return RunOutcome(state="succeeded", **base)


def _ask_model(registry: ToolRegistry, state: _State, ctx: RunContext) -> str:
    """지휘 모델에게 다음 code_tool을 묻는다. 도구 목록은 code_tool만 보여 준다."""
    tools = "\n".join(f"- {t.name}" for t in registry.list(kind="code_tool"))
    done = ", ".join(state["results"]) or "(없음)"
    r = call_model(STEP, {"tools": tools, "results": done}, NextAction, ctx=ctx)
    return r.parsed.next_tool
