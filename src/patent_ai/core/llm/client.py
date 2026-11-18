"""모델 호출의 유일한 입구. 설정·프롬프트 파일을 거쳐 전송층을 부른다.

캐시는 cache 인자로 받는다(없으면 안 씀). 호출 상한(budget)·기록(recorder)·재시도도 여기서 한다.
"""

import json
import time
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from patent_ai.core.llm.cache import Cache, FileCache, make_cache_key
from patent_ai.core.llm.config import REPO_ROOT, load_step_config
from patent_ai.core.llm.errors import (
    ModelCallFailed,
    ModelCallLimitExceeded,
    ModelConfigError,
    ModelOutputInvalid,
    RecordingMissing,
)
from patent_ai.core.llm.limits import CallBudget, CallRecorder
from patent_ai.core.llm.prompts import render_prompt
from patent_ai.core.llm.transport import Transport, TransportError, TransportResponse


class ModelResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    parsed: BaseModel | None
    model: str
    input_tokens: int
    output_tokens: int
    cost: float | None
    elapsed_ms: int
    from_cache: bool


def call_model(
    step: str,
    variables: dict,
    output_schema: type[BaseModel] | None,
    run_id: str,
    attempt: int = 1,
    *,
    transport: Transport | None = None,
    cache: Cache | bool | None = None,
    config_dir: Path | None = None,
    root: Path | None = None,
    budget: CallBudget | None = None,
    recorder: CallRecorder | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> ModelResult:
    root = root or REPO_ROOT
    # 진짜 전송층이면 실행마다 새 CallBudget을 받아야 한다 (전역으로 세면 실행끼리 섞임)
    if budget is None:
        if transport is None:
            raise ModelConfigError("실행마다 CallBudget을 넘겨야 함 (budget=None)")
        budget = CallBudget()  # 가짜 전송층: 그 호출만의 새 budget
    cfg = load_step_config(step, config_dir)
    prompt = render_prompt(cfg.prompt, variables, root)

    # 진짜 전송층이면 기본 파일 캐시를 쓴다 (과금 방지). 끄려면 cache=False
    if cache is None and transport is None:
        cache = FileCache()
    if cache is False:
        cache = None

    # 캐시 키: 프롬프트 파일 원문 해시 + 변수 + 설정 값 + attempt
    try:
        key = make_cache_key(
            step=step,
            model=cfg.model,
            prompt_template=(root / cfg.prompt).read_text(encoding="utf-8"),
            variables=variables,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            attempt=attempt,
        )
    except TypeError as e:
        raise ModelConfigError(f"변수를 JSON으로 바꿀 수 없음: {e}") from e
    hit = cache.get(key) if cache is not None else None

    if hit is None and transport is None:
        from patent_ai.core.llm.transport import AnthropicTransport

        transport = AnthropicTransport()

    # 가격 설정이 둘 다 있을 때만 비용을 계산한다 (캐시 적중은 과금 없음)
    def cost_of(resp: TransportResponse, from_cache: bool) -> float | None:
        if from_cache:
            return 0.0
        if cfg.price_per_mtok_input is None or cfg.price_per_mtok_output is None:
            return None
        return (
            resp.input_tokens * cfg.price_per_mtok_input
            + resp.output_tokens * cfg.price_per_mtok_output
        ) / 1_000_000

    # 호출마다 기록 한 줄 (적중·실패 포함)
    def record(resp, elapsed_ms, from_cache, outcome, transport_try):
        if recorder is None:
            budget.warn_once(
                run_id, step, "no_recorder", "%s: recorder가 없어 호출 기록이 빠짐 (run_id=%s)"
            )
            return
        in_tok = resp.input_tokens if resp else 0
        out_tok = resp.output_tokens if resp else 0
        cost = cost_of(resp, from_cache) if resp else None
        recorder.record(
            run_id,
            step,
            cfg.model,
            in_tok,
            out_tok,
            cost,
            elapsed_ms,
            from_cache,
            attempt,
            outcome,
            transport_try,
        )

    start = time.monotonic()
    tries = 0  # 성공한 전송 시도 번호 (캐시 적중은 0)
    if hit is not None:
        # 캐시 적중: 전송층을 부르지 않고 상한에도 세지 않는다
        resp = TransportResponse(hit["text"], hit["input_tokens"], hit["output_tokens"])
    else:
        resp = None
        retries = cfg.max_retries or 0
        for n in range(retries + 1):
            # 다시 부르는 것도 호출 수에 세므로 매번 상한을 본다
            try:
                budget.check(run_id, step, cfg.max_model_calls, cfg.max_input_tokens)
            except ModelCallLimitExceeded:
                record(None, int((time.monotonic() - start) * 1000), False, "limit_exceeded", n + 1)
                raise
            try_start = time.monotonic()
            try:
                resp = transport.complete(
                    step=step,
                    model=cfg.model,
                    prompt=prompt,
                    temperature=cfg.temperature,
                    max_tokens=cfg.max_tokens,
                )
            except RecordingMissing:
                raise  # 녹화 없음은 조용히 감싸지 않고 그대로 멈춘다
            except Exception as e:
                # TransportError 말고 모르는 예외도 기록하고 세고 ModelCallFailed로 감싼다
                budget.add(run_id, step, 0)
                record(
                    None,
                    int((time.monotonic() - try_start) * 1000),
                    False,
                    "transport_error",
                    n + 1,
                )
                known_retryable = isinstance(e, TransportError) and e.retryable
                if not known_retryable or n == retries:
                    raise ModelCallFailed(f"{step}: {e} (시도 {n + 1}번)") from e
                sleep(2.0**n)  # 1초, 2초, 4초... 쉬었다가 다시
                continue
            budget.add(run_id, step, resp.input_tokens)
            tries = n + 1
            break
    elapsed_ms = int((time.monotonic() - start) * 1000)

    # 스키마가 있으면 답을 JSON으로 읽어 Pydantic 검사한다
    parsed = None
    if output_schema is not None:
        try:
            parsed = output_schema.model_validate(json.loads(resp.text))
        except json.JSONDecodeError as e:
            record(resp, elapsed_ms, hit is not None, "invalid_output", tries)
            raise ModelOutputInvalid(f"답이 JSON이 아님: {e}") from e
        except ValidationError as e:
            record(resp, elapsed_ms, hit is not None, "invalid_output", tries)
            raise ModelOutputInvalid(f"스키마 검사 실패: {e}") from e

    # 검사를 통과한 답만 캐시에 쓴다 (위에서 예외가 나면 여기까지 오지 않음)
    if cache is not None and hit is None:
        cache.put(
            key,
            {
                "text": resp.text,
                "input_tokens": resp.input_tokens,
                "output_tokens": resp.output_tokens,
            },
        )

    record(resp, elapsed_ms, hit is not None, "ok" if hit is None else "cache_hit", tries)
    cost = cost_of(resp, hit is not None)

    return ModelResult(
        text=resp.text,
        parsed=parsed,
        model=cfg.model,
        input_tokens=resp.input_tokens,
        output_tokens=resp.output_tokens,
        cost=cost,
        elapsed_ms=elapsed_ms,
        from_cache=hit is not None,
    )
