"""tool use 한 차례의 호출 길. 차례 한 번 = 호출 한 번 = 상한 한 번 = 캐시 키 하나 = 기록 한 줄.

call_model과 같은 선(상한·캐시·기록·재시도)을 지키되, 답이 글이 아니라 블록 목록(text·tool_use·
thinking)이고 입력이 messages·tools라서 따로 둔다. call_model의 동작·캐시 키는 건드리지 않는다.
"""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from patent_ai.core.llm.cache import FileCache, make_turn_cache_key
from patent_ai.core.llm.client import _warn_no_recorder
from patent_ai.core.llm.config import REPO_ROOT, load_step_config
from patent_ai.core.llm.errors import (
    TRUNCATED_STOP_REASON,
    ModelCallFailed,
    ModelCallLimitExceeded,
    ModelConfigError,
    ModelOutputInvalid,
    RecordingMissing,
)
from patent_ai.core.llm.limits import CallRecord, RunContext
from patent_ai.core.llm.prompts import render_prompt
from patent_ai.core.llm.transport import (
    AnthropicTransport,
    ConverseResponse,
    TransportError,
    is_real_transport,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TurnResult:
    content: list[dict]  # API 답 블록 그대로 (다음 차례 messages에 고치지 않고 돌려준다)
    model: str
    input_tokens: int
    output_tokens: int
    cost: float | None
    elapsed_ms: int
    from_cache: bool
    stop_reason: str | None


def _json_bytes(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def _input_upper_bound(system: str, messages: list[dict], tools: list[dict]) -> int:
    """청구된 입력 토큰을 모를 때 budget에 셀 양. 토큰 하나는 1바이트 이상이라
    system + messages + tools의 UTF-8 바이트 수는 입력 토큰 수보다 작지 않다."""
    return len(system.encode("utf-8")) + _json_bytes(messages) + _json_bytes(tools)


def call_model_turn(
    step: str,
    system_variables: dict,
    messages: list[dict],
    tools: list[dict],
    *,
    ctx: RunContext | None,
    config_dir: Path | None = None,
    root: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> TurnResult:
    root = root or REPO_ROOT
    if ctx is None:
        raise ModelConfigError("ctx가 없음 (RunContext 필요)")
    run_id, budget, recorder = ctx.run_id, ctx.budget, ctx.recorder
    transport, cache = ctx.transport, ctx.cache
    cfg = load_step_config(step, config_dir)
    system = render_prompt(cfg.prompt, system_variables, root)

    # 진짜 전송층이면 기본 파일 캐시 (과금 방지). 가짜는 cache가 없으면 캐시를 안 쓴다
    if cache is None and is_real_transport(transport):
        cache = FileCache()
    if cache is False:
        cache = None

    try:
        key = make_turn_cache_key(
            step=step,
            model=cfg.model,
            prompt_template=(root / cfg.prompt).read_text(encoding="utf-8"),
            system_variables=system_variables,
            messages=messages,
            tools=tools,
            effort=cfg.effort,
            max_tokens=cfg.max_tokens,
        )
    except TypeError as e:
        raise ModelConfigError(f"변수·messages·tools를 JSON으로 바꿀 수 없음: {e}") from e
    hit = cache.get(key) if cache is not None else None

    # 진짜 전송층을 부를 차례면 호출 수 상한이 꼭 있어야 한다 (call_model과 같은 선)
    if hit is None and is_real_transport(transport) and cfg.max_model_calls is None:
        raise ModelConfigError(
            f"{step}: 진짜 전송층을 부르는데 설정에 max_model_calls가 없음 (config/에 넣는다)"
        )
    if hit is None and transport is None:
        transport = AnthropicTransport()

    def cost_of(in_tok: int | None, out_tok: int | None, from_cache: bool) -> float | None:
        if from_cache:
            return 0.0
        if cfg.price_per_mtok_input is None or cfg.price_per_mtok_output is None:
            return None
        if in_tok is None or out_tok is None:  # 끊긴 스트림: 비용도 확인되지 않음
            return None
        return (in_tok * cfg.price_per_mtok_input + out_tok * cfg.price_per_mtok_output) / 1_000_000

    # 호출마다 기록 한 줄. in_tok·out_tok가 None이면 확인되지 않음
    def record(in_tok, out_tok, elapsed_ms, from_cache, outcome, transport_try, stop_reason=None):
        if recorder is None:
            _warn_no_recorder(run_id, step)
            return
        recorder.record(
            CallRecord(
                run_id=run_id,
                step=step,
                model=cfg.model,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cost=cost_of(in_tok, out_tok, from_cache),
                elapsed_ms=elapsed_ms,
                from_cache=from_cache,
                attempt=1,
                outcome=outcome,
                transport_try=transport_try,
                stop_reason=stop_reason,
            )
        )

    start = time.monotonic()
    tries = 0  # 성공한 전송 시도 번호 (캐시 적중은 0)
    if hit is not None:
        # 캐시 적중: 전송층을 부르지 않고 상한에도 세지 않는다
        resp = ConverseResponse(
            hit["content"], hit["input_tokens"], hit["output_tokens"], hit.get("stop_reason")
        )
    else:
        resp = None
        retries = cfg.max_retries or 0
        for n in range(retries + 1):
            # 다시 부르는 것도 호출 수에 세므로 매번 상한을 본다
            try:
                budget.check(run_id, step, cfg.max_model_calls, cfg.max_input_tokens)
            except ModelCallLimitExceeded:
                # 상한에 걸려 부르지 않았으니 토큰은 0
                elapsed = int((time.monotonic() - start) * 1000)
                record(0, 0, elapsed, False, "limit_exceeded", n + 1)
                raise
            try_start = time.monotonic()
            try:
                resp = transport.converse(
                    step=step,
                    model=cfg.model,
                    system=system,
                    messages=messages,
                    tools=tools,
                    effort=cfg.effort,
                    max_tokens=cfg.max_tokens,
                )
            except RecordingMissing, ModelConfigError:
                raise
            except Exception as e:
                usage = e.usage if isinstance(e, TransportError) else None
                failed_ms = int((time.monotonic() - try_start) * 1000)
                if usage is None:
                    # 받은 usage가 없음: 기록은 "확인되지 않음", budget은 위 한계로 센다
                    budget.add(run_id, step, _input_upper_bound(system, messages, tools))
                    record(None, None, failed_ms, False, "transport_error", n + 1)
                else:
                    budget.add(run_id, step, usage.input_tokens)
                    record(
                        usage.input_tokens, usage.output_tokens, failed_ms, False,
                        "transport_error", n + 1,
                    )  # fmt: skip
                known_retryable = isinstance(e, TransportError) and e.retryable
                if not known_retryable or n == retries:
                    raise ModelCallFailed(f"{step}: {e} (시도 {n + 1}번)") from e
                sleep(2.0**n)  # 1초, 2초, 4초... 쉬었다가 다시
                continue
            budget.add(run_id, step, resp.input_tokens)
            tries = n + 1
            break
    elapsed_ms = int((time.monotonic() - start) * 1000)

    # max_tokens에 닿아 잘린 답은 tool_use 입력이 끝까지 안 왔을 수 있다: 쓰지 않고 캐시에도 안 쓴다
    if resp.stop_reason == TRUNCATED_STOP_REASON:
        record(
            resp.input_tokens, resp.output_tokens, elapsed_ms, hit is not None,
            "output_truncated", tries, TRUNCATED_STOP_REASON,
        )  # fmt: skip
        raise ModelOutputInvalid(
            f"{step}: 답이 max_tokens에서 잘림", TRUNCATED_STOP_REASON, "truncated"
        )

    # 성공한 답만 캐시에 쓴다
    if cache is not None and hit is None:
        cache.put(
            key,
            {
                "content": resp.content,
                "input_tokens": resp.input_tokens,
                "output_tokens": resp.output_tokens,
                "stop_reason": resp.stop_reason,
            },
        )

    from_cache = hit is not None
    record(
        resp.input_tokens, resp.output_tokens, elapsed_ms, from_cache,
        "cache_hit" if from_cache else "ok", tries, resp.stop_reason,
    )  # fmt: skip
    return TurnResult(
        content=resp.content,
        model=cfg.model,
        input_tokens=resp.input_tokens,
        output_tokens=resp.output_tokens,
        cost=cost_of(resp.input_tokens, resp.output_tokens, from_cache),
        elapsed_ms=elapsed_ms,
        from_cache=from_cache,
        stop_reason=resp.stop_reason,
    )
