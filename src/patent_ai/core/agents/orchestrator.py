"""지휘 그래프 뼈대와 run_case(). 서버는 run_case 하나만 부른다.

그래프: extract_pages(늘 처음) -> decide -> read_oa -> decide -> ... -> cut_to_oa -> 끝
- decide: plan=agent면 모델이 다음 code_tool을 고르고, plan=fixed_order면 설정 순서대로.
- fixed_order 단계의 도구가 아직 없으면: 설정 skip_if_missing에 있는 이름만 "확인되지 않음"으로
  넘기고(경고 + 단계 기록에 이유), 없는 이름은 설정 오류로 failed (오타를 조용히 넘기지 않는다).
- cut_to_oa(fixed_stage)는 decide가 stop을 낼 때 그래프 간선으로 늘 지난다 (지휘가 고르지 못함).
- 도구가 실패하면 그 자리에서 끝내고 state=failed (성공으로 끝나지 않는다).
"""

import logging
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol, TypedDict

import yaml
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ValidationError

from patent_ai.core.agents.steps import SKIP_PREFIX, StepRecord, StepRecorder
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
    """서버가 넣어 주는 사건 저장소 (core는 api를 import하지 않는다). 같은 OA 확인에 쓴다."""

    def find_oa(self, application_number: str, dispatch_number: str) -> tuple[str, str] | None:
        """같은 출원번호 + 발송번호의 OA가 이미 있으면 (case_id, oa_id)."""
        ...

    def find_case(self, application_number: str) -> str | None:
        """같은 출원번호의 기존 사건이 있으면 case_id."""
        ...


class WaitingFor(StrEnum):
    """사람을 기다리는 이유."""

    APPLICATION_NUMBER = "application_number"
    DISPATCH_NUMBER = "dispatch_number"
    DIRECTION_SELECTION = "direction_selection"


class RunOutcome(BaseModel):
    state: Literal["succeeded", "failed", "waiting_for_human"]
    results: dict[str, Any] = {}  # 도구 이름 -> 결과 객체
    waiting_for: WaitingFor | None = None
    error: dict | None = None  # {code, message} (+ oa_already_exists면 case_id, oa_id)
    searched_scope: list[str] | None = None  # max_steps로 실패했을 때 찾아본 도구 목록
    trace: list[str] = []  # 돈 도구 순서 (되풀이 포함)
    # 돌리지 않고 넘긴 단계: 이름 -> 이유. state가 succeeded여도 이 단계들의 결과는 없다
    skipped: dict[str, str] = {}
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
    skipped: dict[str, str]  # 넘긴 단계 이름 -> 이유


def _name_list(cfg: dict, key: str) -> list[str]:
    """설정의 이름 목록 칸을 읽는다. 목록이 아니거나 글자가 아닌 것이 있으면 멈춘다."""
    value = cfg.get(key, [])
    if not isinstance(value, list) or not all(isinstance(n, str) for n in value):
        raise ValueError(f"{key}는 단계 이름(글자) 목록이어야 함: {value!r}")
    return value


def _error(code: str, message: str) -> dict:
    return {"code": code, "message": message}


def run_case(
    case_input: CaseInput,
    oa_id: str,
    run_id: str,
    store: CaseStore,
    config_path: Path,
    *,
    ctx: RunContext,
    steps: StepRecorder,
) -> RunOutcome:
    """사건 1건을 그래프로 돌려 RunOutcome을 돌려준다. ctx·steps는 서버가 실행마다 만든다."""
    if store is None:
        raise ValueError("store는 필수 (같은 OA 확인에 쓴다)")
    if steps is None:
        raise ValueError("steps는 필수 (단계 기록이 조용히 0줄이 되지 않게)")
    if run_id != ctx.run_id:
        raise ValueError(f"run_id {run_id!r}가 ctx.run_id {ctx.run_id!r}와 다름")
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    plan = cfg.get("plan", "agent")
    if plan not in ("agent", "fixed_order"):
        raise ValueError(f"plan은 agent 또는 fixed_order여야 함: {plan!r}")
    fixed_order = _name_list(cfg, "fixed_order")
    skip_if_missing = set(_name_list(cfg, "skip_if_missing"))
    if plan == "fixed_order" and not fixed_order:
        logger.warning("run_case %s: fixed_order가 비어 있음 (돌릴 단계가 없음)", run_id)
    max_steps: int = cfg.get("max_steps", 10)

    registry = ToolRegistry()
    register_f1_tools(registry)
    code_tools = {t.name for t in registry.list(kind="code_tool")}
    registered = {t.name for t in registry.list()}
    trace: list[str] = []  # 돈 도구 순서 (되풀이 포함)

    def note(kind, name, reason, outcome, status=None, calls=None) -> None:
        """단계 기록 한 줄."""
        steps.record(
            StepRecord(
                run_id=run_id,
                step_kind=kind,
                tool_name=name,
                reason=reason,
                result_status=status,
                model_call_count=calls,
                outcome=outcome,
            )
        )

    def skip(name: str, skipped: dict[str, str], why: str) -> dict[str, str]:
        """단계를 돌리지 않고 넘긴다: 경고 + 단계 기록(확인되지 않음 + 이유). ok로 적지 않는다."""
        logger.warning("run_case %s: %s 단계를 넘김 (확인되지 않음): %s", run_id, name, why)
        # 넘긴 이유는 reason 칸에 담는다 (새 칸·새 outcome 값은 DB agent_steps를 바꿔야 해서 안 둠)
        note("code_tool", name, f"{SKIP_PREFIX}{why}", "waiting", StatusValue.UNVERIFIED.value)
        return {**skipped, name: why}

    def model_calls() -> int | None:
        """실제 전송 시도 수. records 없는 기록기는 셀 수 없어 None (0으로 속이지 않음)."""
        records = getattr(ctx.recorder, "records", None)
        if records is None:
            return None
        sent = ("ok", "invalid_output", "transport_error")  # cache_hit·limit_exceeded는 안 셈
        return sum(1 for r in records if r.run_id == run_id and r.outcome in sent)

    def calls_since(before: int | None) -> int | None:
        after = model_calls()
        return None if before is None or after is None else after - before

    def call_tool(name: str, state: _State, payload: dict, reason: str) -> dict:
        """도구 하나를 돌려 결과를 상태에 쌓는다. 실패하면 error를 채운다."""
        tool = registry.get(name)
        before = model_calls()
        try:
            out = tool.run(payload, ctx)
        except _TOOL_ERRORS as e:
            note(tool.kind, name, reason, "failed", calls=calls_since(before))
            return {"error": _error(type(e).__name__, str(e))}
        note(tool.kind, name, reason, "ok", out.status.value, calls_since(before))
        trace.append(name)
        # 자르기(fixed_stage)는 지휘가 고른 것이 아니라서 max_steps에 세지 않는다
        counted = tool.kind == "code_tool"
        return {
            "results": {**state["results"], name: out.result},
            "steps": state["steps"] + (1 if counted else 0),
        }

    # ---- 노드 ----
    def extract_pages_node(state: _State) -> dict:
        return call_tool(
            "extract_pages",
            state,
            {"pdf_path": case_input.oa_document, "document_id": case_input.oa_document_id},
            "고정 단계",
        )

    def decide_node(state: _State) -> dict:
        skipped = state["skipped"]
        if plan == "fixed_order":
            reason, calls = "고정 순서", None
            todo = [n for n in fixed_order if n not in state["results"] and n not in skipped]
            # 도구가 아직 없는 단계: 설정에 넘겨도 된다고 적힌 이름만 넘기고 다음 단계로 간다
            while todo and todo[0] not in registered and todo[0] in skip_if_missing:
                why = "tool_missing: 등록된 도구가 없음 (설정 skip_if_missing에 있어 넘김)"
                skipped = skip(todo.pop(0), skipped, why)
            choice = todo[0] if todo else "stop"
        else:
            before = model_calls()
            try:
                action = _ask_model(registry, state, ctx)
            except _TOOL_ERRORS as e:
                note("decide", "?", "지휘 모델 실패", "failed", calls=calls_since(before))
                return {"error": _error(type(e).__name__, str(e))}
            choice, reason, calls = action.next_tool, action.reason, calls_since(before)

        def reject(code: str, message: str) -> dict:
            note("decide", choice, reason, "failed", calls=calls)
            return {"error": _error(code, message), "skipped": skipped}

        if choice == "stop":
            # 자르기는 read_oa 뒤 간선에서 이미 돌았다. read_oa 없이 멈추면 실패
            if "read_oa" not in state["results"]:
                return reject("no_oa_result", "read_oa 없이 멈춤")
        # 지휘가 고를 수 있는 것은 code_tool뿐 (fixed_stage·없는 이름·이미 돈 read_oa는 거부)
        elif choice not in code_tools or (choice == "read_oa" and "read_oa" in state["results"]):
            hint = ""
            if plan == "fixed_order" and choice not in registered:
                # 오타인지 아직 없는 단계인지 코드가 짐작하지 않는다: 표시가 없으면 설정 오류
                hint = " (등록된 도구가 아니고 설정 skip_if_missing에도 없음)"
            return reject("invalid_tool_choice", f"고를 수 없는 도구: {choice}{hint}")
        # 끝내자고 하지 않았는데 상한에 닿았으면 못 끝낸 것: 성공으로 두지 않는다
        elif state["steps"] >= max_steps:
            return reject(
                "max_steps", f"도구 호출 최대 {max_steps}번에 닿음. 돈 도구: {', '.join(trace)}"
            )
        if plan == "agent":  # 고정 순서는 모델 판단이 없어 성공 줄을 남기지 않는다
            note("decide", choice, reason, "ok", calls=calls)
        return {"next_tool": choice, "skipped": skipped}

    def check_oa_node(state: _State) -> dict:
        """read_oa 뒤 검사: 번호를 모르면 사람을 기다리고, 이미 있는 OA면 실패로 끝낸다."""
        oa = state["results"]["read_oa"]
        app, disp = oa.application_number, oa.dispatch_number
        if app.status.value != StatusValue.CONFIRMED:  # unverified·conflict
            note("check", "check_oa", "출원번호를 몰라 사람을 기다림", "waiting")
            return {"waiting_for": WaitingFor.APPLICATION_NUMBER}
        # 발송번호를 모르면 같은 OA인지 판정할 수 없어 사람에게 묻는다
        if disp.status.value != StatusValue.CONFIRMED:
            note("check", "check_oa", "발송번호를 몰라 사람을 기다림", "waiting")
            return {"waiting_for": WaitingFor.DISPATCH_NUMBER}
        found = store.find_oa(app.value, disp.value)
        if found is not None:
            case_id, found_oa_id = found
            note("check", "check_oa", f"이미 있는 OA: {found_oa_id}", "failed")
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
            "고정 순서" if plan == "fixed_order" else "지휘 선택",
        )

    def cut_node(state: _State) -> dict:
        return call_tool("cut_to_oa", state, {"materials": case_input.materials}, "고정 단계")

    # ---- 간선 ----
    def after_decide(s: _State) -> str:
        if s["error"] or s["next_tool"] == "stop":
            return END
        return s["next_tool"]

    def after_check(s: _State) -> str:
        return END if s["error"] or s["waiting_for"] else "cut_to_oa"

    g = StateGraph(_State)
    g.add_node("extract_pages", extract_pages_node)
    g.add_node("decide", decide_node)
    g.add_node("read_oa", read_oa_node)
    g.add_node("check_oa", check_oa_node)
    g.add_node("cut_to_oa", cut_node)
    g.add_edge(START, "extract_pages")
    g.add_conditional_edges(
        "extract_pages", lambda s: END if s["error"] else "decide", ["decide", END]
    )
    g.add_conditional_edges("decide", after_decide, ["extract_pages", "read_oa", END])
    g.add_conditional_edges(
        "read_oa", lambda s: END if s["error"] else "check_oa", ["check_oa", END]
    )
    # read_oa → check_oa → cut_to_oa 는 고정 간선: 지휘가 건너뛸 수 없다
    g.add_conditional_edges("check_oa", after_check, ["cut_to_oa", END])
    g.add_conditional_edges("cut_to_oa", lambda s: END if s["error"] else "decide", ["decide", END])

    try:
        final = g.compile().invoke(
            {
                "results": {},
                "steps": 0,
                "next_tool": None,
                "error": None,
                "waiting_for": None,
                "case_id": case_input.case_id,
                "skipped": {},
            }
        )
    except Exception:
        # 목록 밖 예외(버그)는 숨기지 않고 던진다. 던지기 전에 어디까지 돌았는지 남긴다
        logger.exception("run_case %s 예외, 지금까지 돈 도구: %s", run_id, trace)
        raise

    base = {
        "results": final["results"],
        "case_id": final["case_id"],
        "trace": list(trace),
        "skipped": final["skipped"],
    }
    if final["error"]:
        logger.warning("run_case %s 실패: %s", run_id, final["error"])
        scope = list(trace) if final["error"]["code"] == "max_steps" else None
        return RunOutcome(state="failed", error=final["error"], searched_scope=scope, **base)
    if final["waiting_for"]:
        return RunOutcome(state="waiting_for_human", waiting_for=final["waiting_for"], **base)
    return RunOutcome(state="succeeded", **base)


def _ask_model(registry: ToolRegistry, state: _State, ctx: RunContext) -> NextAction:
    """지휘 모델에게 다음 code_tool을 묻는다. 도구 목록은 code_tool만 보여 준다."""
    tools = "\n".join(f"- {t.name}" for t in registry.list(kind="code_tool"))
    done = ", ".join(state["results"]) or "(없음)"
    r = call_model(STEP, {"tools": tools, "results": done}, NextAction, ctx=ctx)
    return r.parsed
