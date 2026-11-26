"""모델 호출의 유일한 입구. 설정·프롬프트 파일을 거쳐 전송층을 부른다.

실행 맥락(ctx)이나 따로 넘긴 인자로 run_id·budget·recorder·transport·cache를 받는다.
호출 상한(budget)·기록(recorder)·재시도도 여기서 한다.
"""

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import get_args

from pydantic import BaseModel, ConfigDict, ValidationError

from patent_ai.core.llm.cache import Cache, FileCache, make_cache_key
from patent_ai.core.llm.config import REPO_ROOT, load_step_config
from patent_ai.core.llm.errors import (
    TRUNCATED_STOP_REASON,
    ModelCallFailed,
    ModelCallLimitExceeded,
    ModelConfigError,
    ModelOutputInvalid,
    RecordingMissing,
)
from patent_ai.core.llm.json_answer import parse_answer
from patent_ai.core.llm.limits import CallBudget, CallRecord, CallRecorder, RunContext
from patent_ai.core.llm.prompts import render_prompt
from patent_ai.core.llm.transport import (
    AnthropicTransport,
    Transport,
    TransportError,
    TransportResponse,
    is_real_transport,
)

logger = logging.getLogger(__name__)

# 기록기가 없다는 경고를 이미 남긴 (run_id, step). 로그 중복 막기용이고 호출 결과엔 영향 없음
_warned_no_recorder: set[tuple[str, str]] = set()


def _warn_no_recorder(run_id: str, step: str) -> None:
    if (run_id, step) not in _warned_no_recorder:
        _warned_no_recorder.add((run_id, step))
        logger.warning("%s: recorder가 없어 호출 기록이 빠짐 (run_id=%s)", step, run_id)


def _input_tokens_upper_bound(prompt: str) -> int:
    """청구된 입력 토큰을 모를 때 budget에 셀 양. 토큰 하나는 1바이트 이상이라
    프롬프트의 UTF-8 바이트 수는 입력 토큰 수보다 작지 않다 (적게 세지 않게)."""
    return len(prompt.encode("utf-8"))


# 출력 검사 오류 종류 짧은 코드 (#228). 기록에 이 순서로 잇는다
_INVALID_KIND_ORDER = ("not_json", "unknown_key", "missing_key", "bad_value")
# Pydantic 오류 type -> 짧은 코드. 여기 없는 type(타입·값·모양 틀림)은 모두 bad_value
_PYDANTIC_KIND = {"extra_forbidden": "unknown_key", "missing": "missing_key"}


def _not_json_kind(text: str) -> str:
    """JSON이 아닌 답의 모양만 짧은 코드로 (#317). 답 글자는 남기지 않는다.

    empty = 빈 답(공백뿐) / fence = 코드 블록(```)으로 시작 / broken = `{`·`[`로 시작했지만
    JSON이 깨짐(잘림 포함) / text = 그 밖의 글(설명 글 등)로 시작.
    """
    head = text.lstrip()
    if not head:
        return "not_json:empty"
    if head.startswith("```"):
        return "not_json:fence"
    if head[0] in "{[":
        return "not_json:broken"
    return "not_json:text"


def _model_in(annotation) -> type[BaseModel] | None:
    """칸 타입 안의 Pydantic 모델 하나를 찾는다 (list[Row]·Row | None -> Row). 없으면 None."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for arg in get_args(annotation):
        found = _model_in(arg)
        if found is not None:
            return found
    return None


def _schema_path(schema: type[BaseModel], loc: tuple) -> str:
    """오류 위치(loc)에서 우리 스키마에 있는 칸 이름만 골라 점으로 잇는다 (#228 리뷰).

    리스트 번호는 건너뛴다. 스키마 칸이 아닌 글자(모르는 키, dict 칸의 키)를 만나면 거기서
    멈춘다: 그 글자는 모델이 쓴 원문이라 기록·로그에 남기지 않는다.
    """
    names: list[str] = []
    model: type[BaseModel] | None = schema
    for part in loc:
        if isinstance(part, int):
            continue  # 리스트 번호
        if model is None or part not in model.model_fields:
            break
        names.append(part)
        model = _model_in(model.model_fields[part].annotation)
    return ".".join(names)


def _schema_errors(schema: type[BaseModel], e: ValidationError) -> list[tuple[str, str, str]]:
    """검사 오류마다 (종류 코드, 스키마 칸 경로, Pydantic 설명). 답 글자(input)는 안 담는다."""
    return [
        (
            _PYDANTIC_KIND.get(err["type"], "bad_value"),
            _schema_path(schema, err["loc"]),
            err["msg"],
        )
        for err in e.errors(include_url=False, include_input=False, include_context=False)
    ]


def _invalid_kind(errors: list[tuple[str, str, str]]) -> str:
    """오류 종류 코드를 기록용 한 줄로. 칸이 있으면 `종류:칸`, 겹치면 한 번만,
    종류 순서 다음 칸 이름 순서로 쉼표로 잇는다 (예: missing_key:title,bad_value:rows.number)."""
    entries = {(kind, path) for kind, path, _ in errors}
    ordered = sorted(entries, key=lambda kp: (_INVALID_KIND_ORDER.index(kp[0]), kp[1]))
    return ",".join(f"{kind}:{path}" if path else kind for kind, path in ordered)


def _schema_error_message(errors: list[tuple[str, str, str]]) -> str:
    """다시 부르는 프롬프트·단계 기록에 가는 오류 설명. 칸과 이유만, 답 글자는 없음."""
    lines = [f"{path or '(전체)'}: {msg}" for _, path, msg in errors]
    return f"{len(errors)}개 오류\n" + "\n".join(lines)


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
    run_id: str | None = None,
    attempt: int = 1,
    *,
    ctx: RunContext | None = None,
    transport: Transport | None = None,
    cache: Cache | bool | None = None,
    config_dir: Path | None = None,
    root: Path | None = None,
    budget: CallBudget | None = None,
    recorder: CallRecorder | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> ModelResult:
    root = root or REPO_ROOT
    if ctx is not None:
        # ctx가 있으면 따로 넘긴 인자와 섞지 않는다 (어느 쪽이 맞는지 헷갈리지 않게)
        given = [
            n
            for n, v in (
                ("run_id", run_id),
                ("transport", transport),
                ("cache", cache),
                ("budget", budget),
                ("recorder", recorder),
            )
            if v is not None
        ]
        if given:
            raise ModelConfigError(f"ctx와 {given}를 같이 줄 수 없음")
        run_id, budget, recorder = ctx.run_id, ctx.budget, ctx.recorder
        transport, cache = ctx.transport, ctx.cache
    if run_id is None:
        raise ModelConfigError("run_id가 없음 (run_id 또는 ctx 필요)")
    # 상한은 실행마다 새 CallBudget이 있어야 센다 (없으면 상한이 조용히 빠짐)
    if budget is None:
        raise ModelConfigError("실행마다 CallBudget을 넘겨야 함 (budget=None)")
    cfg = load_step_config(step, config_dir)
    prompt = render_prompt(cfg.prompt, variables, root)
    # system 칸 (설정에 system_prompt가 있을 때만). 변수 없는 고정 글이라 빈 변수로 채운다:
    # 자리표시자가 있으면 render_prompt가 "변수가 빠짐" 설정 오류로 멈춘다
    system = render_prompt(cfg.system_prompt, {}, root) if cfg.system_prompt else None

    # 진짜 전송층(AnthropicTransport)이면 기본 파일 캐시를 쓴다 (과금 방지). 끄려면 cache=False
    # 가짜 등 그 밖의 전송층은 cache=None이면 캐시를 안 쓴다
    if cache is None and is_real_transport(transport):
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
            effort=cfg.effort,
            max_tokens=cfg.max_tokens,
            attempt=attempt,
            system_template=system,
        )
    except TypeError as e:
        raise ModelConfigError(f"변수를 JSON으로 바꿀 수 없음: {e}") from e
    hit = cache.get(key) if cache is not None else None

    # 진짜 전송층을 부를 차례면(캐시 적중 아님) 호출 수 상한이 꼭 있어야 한다 (과금 방지).
    # 가짜·기록 전송층은 돈이 안 들어 지금처럼 경고만 한다 (CallBudget.check)
    calls_real = is_real_transport(transport)
    if hit is None and calls_real and cfg.max_model_calls is None:
        raise ModelConfigError(
            f"{step}: 진짜 전송층을 부르는데 설정에 max_model_calls가 없음 (config/에 넣는다)"
        )
    if hit is None and transport is None:
        transport = AnthropicTransport()

    # 가격 설정이 둘 다 있을 때만 비용을 계산한다 (캐시 적중은 과금 없음)
    # 토큰 하나라도 모르면(None, 끊긴 스트림) 비용도 확인되지 않음 (#194)
    def cost_of_tokens(in_tok: int | None, out_tok: int | None, from_cache: bool) -> float | None:
        if from_cache:
            return 0.0
        if cfg.price_per_mtok_input is None or cfg.price_per_mtok_output is None:
            return None
        if in_tok is None or out_tok is None:
            return None
        return (in_tok * cfg.price_per_mtok_input + out_tok * cfg.price_per_mtok_output) / 1_000_000

    def cost_of(resp: TransportResponse, from_cache: bool) -> float | None:
        return cost_of_tokens(resp.input_tokens, resp.output_tokens, from_cache)

    # 호출마다 기록 한 줄 (적중·실패 포함)
    # 전송 중 실패한 호출: usage = 끊기기 전에 받은 토큰 (출력은 None일 수 있음),
    # usage_unknown=True = 청구된 토큰을 아예 모름 -> 토큰·비용을 None(확인되지 않음)
    def record(
        resp,
        elapsed_ms,
        from_cache,
        outcome,
        transport_try,
        usage=None,
        usage_unknown=False,
        invalid_kind=None,
    ):
        if recorder is None:
            _warn_no_recorder(run_id, step)
            return
        if usage_unknown:
            in_tok = out_tok = cost = None
        elif usage is not None:
            in_tok, out_tok = usage.input_tokens, usage.output_tokens
            cost = cost_of_tokens(in_tok, out_tok, from_cache)
        else:
            in_tok = resp.input_tokens if resp else 0
            out_tok = resp.output_tokens if resp else 0
            cost = cost_of(resp, from_cache) if resp else None
        recorder.record(
            CallRecord(
                run_id=run_id,
                step=step,
                model=cfg.model,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cost=cost,
                elapsed_ms=elapsed_ms,
                from_cache=from_cache,
                attempt=attempt,
                outcome=outcome,
                transport_try=transport_try,
                stop_reason=resp.stop_reason if resp else None,
                invalid_kind=invalid_kind,
            )
        )

    start = time.monotonic()
    tries = 0  # 성공한 전송 시도 번호 (캐시 적중은 0)
    if hit is not None:
        # 캐시 적중: 전송층을 부르지 않고 상한에도 세지 않는다
        # stop_reason 칸이 없는 옛 캐시 파일은 None으로 읽는다
        resp = TransportResponse(
            hit["text"], hit["input_tokens"], hit["output_tokens"], hit.get("stop_reason")
        )
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
                # system은 있을 때만 넘긴다 (system을 모르는 옛 전송층·테스트 가짜도 그대로 돈다)
                extra = {"system": system} if system is not None else {}
                resp = transport.complete(
                    step=step,
                    model=cfg.model,
                    prompt=prompt,
                    effort=cfg.effort,
                    max_tokens=cfg.max_tokens,
                    **extra,
                )
            except RecordingMissing, ModelConfigError:
                raise  # 기록된 응답 없음·설정 잘못은 감싸지 않고 그대로 멈춘다
            except Exception as e:
                # TransportError 말고 모르는 예외도 기록하고 세고 ModelCallFailed로 감싼다
                # 스트림이 중간에 끊겨도 입력·부분 출력은 청구됐을 수 있다 (#194)
                usage = e.usage if isinstance(e, TransportError) else None
                failed_ms = int((time.monotonic() - try_start) * 1000)
                if usage is None:
                    # 받은 usage가 없음: 기록은 "확인되지 않음", budget은 위 한계로 센다
                    budget.add(run_id, step, _input_tokens_upper_bound(prompt))
                    record(None, failed_ms, False, "transport_error", n + 1, usage_unknown=True)
                else:
                    budget.add(run_id, step, usage.input_tokens)
                    # 입력 토큰은 message_start에서 받아 안다. 출력은 모를 수 있다 (None)
                    record(None, failed_ms, False, "transport_error", n + 1, usage=usage)
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
        # 검사에 떨어진 이유를 둘로 나눠 기록한다: max_tokens에 닿아 잘린 답(output_truncated)과
        # 끝까지 답했는데 모양이 틀린 답(invalid_output). 예외에도 stop_reason을 실어 보낸다
        truncated = resp.stop_reason == TRUNCATED_STOP_REASON
        failed = "output_truncated" if truncated else "invalid_output"
        try:
            parsed = output_schema.model_validate(parse_answer(resp.text, truncated=truncated))
        except json.JSONDecodeError as e:
            kind = _not_json_kind(resp.text)
            record(resp, elapsed_ms, hit is not None, failed, tries, invalid_kind=kind)
            raise ModelOutputInvalid(f"답이 JSON이 아님: {e}", resp.stop_reason, kind) from e
        except ValidationError as e:
            errors = _schema_errors(output_schema, e)
            kind = _invalid_kind(errors)
            record(resp, elapsed_ms, hit is not None, failed, tries, invalid_kind=kind)
            # 메시지에 Pydantic 기본 글(str(e))을 쓰지 않는다: 답 일부(input_value)가 들어간다
            message = f"스키마 검사 실패: {_schema_error_message(errors)}"
            raise ModelOutputInvalid(message, resp.stop_reason, kind) from None

    # 검사를 통과한 답만 캐시에 쓴다 (위에서 예외가 나면 여기까지 오지 않음)
    if cache is not None and hit is None:
        cache.put(
            key,
            {
                "text": resp.text,
                "input_tokens": resp.input_tokens,
                "output_tokens": resp.output_tokens,
                "stop_reason": resp.stop_reason,
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
