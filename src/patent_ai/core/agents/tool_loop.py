"""에이전트 공통 도구 루프 (recheck design 4-2·4-3·4-4절).

모델이 도구를 골라 부르고, 코드가 검사·실행해 결과를 돌려주는 일을 끝 도구(submit·give_up)가
불리거나 상한에 닿을 때까지 되풀이한다. 한 차례 = call_model_turn 한 번.
하위 에이전트(f3_claim_compare/recheck 등)가 도구 표와 시스템 프롬프트만 바꿔 끼운다.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from patent_ai.core.llm.errors import (
    ModelCallFailed,
    ModelCallLimitExceeded,
    ModelOutputInvalid,
)
from patent_ai.core.llm.limits import RunContext
from patent_ai.core.llm.turns import call_model_turn

logger = logging.getLogger(__name__)

# API strict 스키마가 받지 않는 제약 키: 싣지 않고 제약은 설명 글과 코드 검사로 한다
_UNSUPPORTED_KEYS = {
    "maxLength",
    "minLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "maxItems",
    "minItems",
    "pattern",
    "title",
    "default",
}

NO_TEXT_ONLY = "도구로만 답한다: 끝낼 때 submit 또는 give_up"


class RecheckToolFailed(Exception):
    """도구 실행이 환경 때문에 실패함 (예: 검색 예외). 루프가 tool_failed로 끝낸다."""


@dataclass(frozen=True)
class GiveUp:
    """give_up 끝 도구가 돌려주는 값."""

    reason: str
    tried: str = ""


@dataclass
class ToolOutcome:
    content: str  # 모델에게 돌려줄 tool_result 글
    is_error: bool = False
    done: object | None = None  # 있으면 루프가 끝난다 (끝 도구가 검사를 통과했을 때만)
    result_ids: list[str] = field(default_factory=list)  # 단계 기록용: 낸 조각 ID
    logged_input: dict = field(default_factory=dict)  # 단계 기록용: 질의·k·ID (문단 글 없음)


def _strict_schema(node):
    """pydantic 스키마를 API strict 모양으로: 제약 키 빼기, 모든 칸 required, 추가 칸 금지."""
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            # properties 안의 칸 이름이 우연히 제약 키 이름이어도 지우지 않는다
            if key == "properties" and isinstance(value, dict):
                out[key] = {name: _strict_schema(sub) for name, sub in value.items()}
            elif key == "$defs" and isinstance(value, dict):
                out[key] = {name: _strict_schema(sub) for name, sub in value.items()}
            elif key in _UNSUPPORTED_KEYS:
                continue
            else:
                out[key] = _strict_schema(value)
        if "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out["properties"])
        return out
    if isinstance(node, list):
        return [_strict_schema(v) for v in node]
    return node


@dataclass
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    run: Callable[[BaseModel], ToolOutcome]
    terminal: bool = False

    def api_definition(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": _strict_schema(self.input_model.model_json_schema()),
            "strict": True,
        }


@dataclass(frozen=True)
class LoopLimits:
    tool_calls: int
    turns: int


@dataclass(frozen=True)
class LoopStep:
    turn: int
    tool_name: str
    logged_input: dict
    result_ids: list[str]
    is_error: bool


Outcome = Literal["submitted", "gave_up", "limit_reached", "model_call_failed", "tool_failed"]


@dataclass
class LoopResult:
    outcome: Outcome
    value: object | None
    steps: list[LoopStep]
    turns: int
    tool_calls: int
    queries: list[str]


def _validation_message(e: ValidationError) -> str:
    # 칸 이름과 이유만. 받은 글자(input)는 넣지 않는다 (문단 글·비공개 글이 되돌려지지 않게)
    parts = []
    for err in e.errors(include_input=False, include_url=False):
        loc = ".".join(str(p) for p in err["loc"]) or "(전체)"
        parts.append(f"{loc}: {err['msg']}")
    return "인자 모양이 틀렸다. " + "; ".join(parts) + ". 정의대로 고쳐 다시 부른다"


def run_tool_loop(
    step: str,
    system_variables: dict,
    first_user: str,
    tools: list[ToolSpec],
    *,
    ctx: RunContext,
    limits: LoopLimits,
    config_dir: Path | None = None,
    root: Path | None = None,
) -> LoopResult:
    by_name = {t.name: t for t in tools}
    definitions = [t.api_definition() for t in tools]
    messages: list[dict] = [{"role": "user", "content": first_user}]
    steps: list[LoopStep] = []
    queries: list[str] = []
    turns = 0
    tool_calls = 0

    def finish(outcome: Outcome, value: object | None = None) -> LoopResult:
        return LoopResult(outcome, value, steps, turns, tool_calls, queries)

    while turns < limits.turns:
        turns += 1
        try:
            result = call_model_turn(
                step,
                system_variables,
                messages,
                definitions,
                ctx=ctx,
                config_dir=config_dir,
                root=root,
            )
        except ModelCallLimitExceeded:
            return finish("limit_reached")
        except (ModelCallFailed, ModelOutputInvalid) as e:
            logger.warning("%s 모델 호출 실패: %s", step, e)
            return finish("model_call_failed")

        # 받은 답 블록은 고치지 않고 다음 차례 messages에 그대로 돌려준다 (thinking 서명 포함)
        messages.append({"role": "assistant", "content": result.content})
        uses = [b for b in result.content if b.get("type") == "tool_use"]
        if not uses:
            # 글만 답함: 도구로만 답하라고 알리고 다음 차례
            messages.append({"role": "user", "content": NO_TEXT_ONLY})
            continue

        results: list[dict] = []
        done: object | None = None
        for use in uses:
            if tool_calls >= limits.tool_calls:
                # 호출 상한에 닿음: 이 도구는 돌리지 않는다
                return finish("limit_reached")
            tool_calls += 1
            spec = by_name.get(use.get("name"))
            if spec is None:
                content = f"없는 도구 {use.get('name')}. 쓸 수 있는 도구: " + ", ".join(by_name)
                steps.append(LoopStep(turns, str(use.get("name")), {}, [], True))
                results.append(_tool_result(use, content, True))
                continue
            try:
                parsed = spec.input_model.model_validate(use.get("input") or {})
            except ValidationError as e:
                steps.append(LoopStep(turns, spec.name, {}, [], True))
                results.append(_tool_result(use, _validation_message(e), True))
                continue
            query = getattr(parsed, "query", None)
            if isinstance(query, str) and query not in queries:
                queries.append(query)
            try:
                outcome = spec.run(parsed)
            except ModelCallLimitExceeded:
                # 도구 안(질의 임베딩)에서 실행 합계 상한에 닿음: 실패가 아니라 상한 끝
                steps.append(LoopStep(turns, spec.name, {}, [], True))
                return finish("limit_reached")
            except RecheckToolFailed as e:
                logger.warning("%s 도구 %s 실행 실패: %s", step, spec.name, e)
                # 어떤 호출이 실패했는지 남긴다 (질의·k만, 문단 글은 없음)
                failed = {
                    key: getattr(parsed, key) for key in ("query", "k") if hasattr(parsed, key)
                }
                steps.append(LoopStep(turns, spec.name, failed, [], True))
                return finish("tool_failed")
            steps.append(
                LoopStep(
                    turns, spec.name, outcome.logged_input, outcome.result_ids, outcome.is_error
                )
            )
            results.append(_tool_result(use, outcome.content, outcome.is_error))
            if outcome.done is not None:
                done = outcome.done
                break  # 끝 도구가 통과했으면 뒤 호출은 돌리지 않는다

        if done is not None:
            return finish("gave_up" if isinstance(done, GiveUp) else "submitted", done)
        if tool_calls >= limits.tool_calls:
            # 호출 상한을 다 씀: tool_result를 붙여 봐야 쓸 곳이 없으니 모델을 더 부르지 않고 끝낸다
            return finish("limit_reached")
        # 한 차례의 tool_result는 user 메시지 하나에 모은다
        messages.append({"role": "user", "content": results})

    return finish("limit_reached")  # 차례 상한


def _tool_result(use: dict, content: str, is_error: bool) -> dict:
    block = {"type": "tool_result", "tool_use_id": use.get("id"), "content": content}
    if is_error:
        block["is_error"] = True
    return block
