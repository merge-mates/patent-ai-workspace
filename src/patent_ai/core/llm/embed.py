"""임베딩(글 → 벡터)의 유일한 입구. call_model과 같은 규칙: 설정 파일, 캐시, 호출 상한, 기록.

- 설정: config/<기능>.yaml 의 <단계> 칸 (model, batch_size, 가격, 상한, max_retries).
- 캐시: 글 하나 = 캐시 한 칸. 진짜 전송층이면 기본 파일 캐시(work/llm_cache).
- 상한: 묶음(batch) 호출 하나를 호출 1번으로 센다. 진짜 전송층을 부를 차례인데
  max_model_calls가 없으면 부르기 전에 ModelConfigError (#108 규칙과 같음).
"""

import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml

from patent_ai.core.llm.cache import Cache, FileCache
from patent_ai.core.llm.config import REPO_ROOT
from patent_ai.core.llm.embed_transport import (
    EmbedTransport,
    GeminiEmbedTransport,
    OpenAIEmbedTransport,
)
from patent_ai.core.llm.errors import (
    ModelCallFailed,
    ModelCallLimitExceeded,
    ModelConfigError,
    ModelOutputInvalid,
    RecordingMissing,
)
from patent_ai.core.llm.limits import CallRecord, RunContext
from patent_ai.core.llm.transport import TransportError, is_real_transport

logger = logging.getLogger(__name__)

KNOWN_KEYS = {
    "model",
    "provider",
    "task_type",
    "dimensions",
    "batch_size",
    "price_per_mtok_input",
    "max_model_calls",
    "max_input_tokens",
    "max_retries",
}


@dataclass(frozen=True)
class EmbedConfig:
    model: str
    batch_size: int = 100
    price_per_mtok_input: float | None = None
    max_model_calls: int | None = None
    max_input_tokens: int | None = None
    max_retries: int | None = None
    provider: str = "openai"
    task_type: str | None = None
    dimensions: int | None = None


def load_embed_config(step: str, config_dir: Path | None = None) -> EmbedConfig:
    feature, dot, name = step.partition(".")
    if not dot or not feature or not name:
        raise ModelConfigError(f"step은 '<기능>.<단계>' 모양이어야 함: {step!r}")
    path = (config_dir or REPO_ROOT / "config") / f"{feature}.yaml"
    if not path.is_file():
        raise ModelConfigError(f"설정 파일이 없음: {path} (step={step})")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    section = data.get(name) if isinstance(data, dict) else None
    if not isinstance(section, dict):
        raise ModelConfigError(f"{path.name}에 단계 {name!r}이 없음 (step={step})")
    for key in section.keys() - KNOWN_KEYS:
        logger.warning("%s: 모르는 설정 키 %r (오타?)", step, key)
    if not section.get("model"):
        raise ModelConfigError(f"{step}에 설정 키가 빠짐: model")

    def number(key: str, kind, default=None):
        if section.get(key) is None:
            return default
        try:
            value = kind(section[key])
        except (TypeError, ValueError) as e:
            raise ModelConfigError(f"{step}의 {key}를 숫자로 못 바꿈: {section[key]!r}") from e
        if value < 0:
            raise ModelConfigError(f"{step}의 {key}는 0 이상이어야 함: {value}")
        return value

    batch = number("batch_size", int, 100)
    if batch < 1:
        raise ModelConfigError(f"{step}의 batch_size는 1 이상이어야 함: {batch}")
    price = number("price_per_mtok_input", float)
    if price is None:
        logger.warning("%s: price(가격) 설정이 없어 비용을 계산하지 않음", step)
    provider = section.get("provider", "openai")
    task_type = section.get("task_type")
    dimensions = number("dimensions", int)
    if provider not in ("openai", "gemini"):
        raise ModelConfigError(f"{step}: 지원하지 않는 임베딩 provider {provider!r}")
    if provider == "gemini":
        if not isinstance(task_type, str) or not task_type.strip() or not dimensions:
            raise ModelConfigError(
                f"{step}: Gemini 임베딩에는 task_type과 양의 dimensions가 필요함"
            )
        if batch > 100:
            raise ModelConfigError(f"{step}: Gemini 임베딩의 batch_size는 최대 100")
    elif task_type is not None or dimensions is not None:
        raise ModelConfigError(f"{step}: task_type과 dimensions는 Gemini 임베딩 설정임")
    return EmbedConfig(
        model=section["model"],
        batch_size=batch,
        price_per_mtok_input=price,
        max_model_calls=number("max_model_calls", int),
        max_input_tokens=number("max_input_tokens", int),
        max_retries=number("max_retries", int),
        provider=provider,
        task_type=task_type,
        dimensions=dimensions,
    )


def _cache_key(step: str, cfg: EmbedConfig, text: str) -> str:
    # call_model 캐시와 키가 겹치지 않게 kind를 넣는다
    fields: dict[str, str | int | None] = dict(kind="embed", step=step, model=cfg.model, text=text)
    if cfg.provider == "gemini":
        fields.update(provider=cfg.provider, task_type=cfg.task_type, dimensions=cfg.dimensions)
    raw = json.dumps(fields, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def embed(
    step: str,
    texts: list[str],
    *,
    ctx: RunContext,
    config_dir: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[list[float]]:
    """글 목록 → 같은 순서의 벡터 목록. 실행 맥락(ctx)의 상한·기록·전송층·캐시를 쓴다."""
    cfg = load_embed_config(step, config_dir)
    if not texts:
        # 목록이 비면 경고를 남긴다 (조용히 끝내지 않음)
        logger.warning("%s: 임베딩할 글이 0개다 (run_id=%s)", step, ctx.run_id)
        return []

    transport: EmbedTransport | None = ctx.transport
    real = is_real_transport(transport)
    # 진짜 전송층이면 기본 파일 캐시 (과금 방지). cache=False면 끔
    cache: Cache | None
    if ctx.cache is False:
        cache = None
    elif ctx.cache is None:
        cache = FileCache() if real else None
    else:
        cache = ctx.cache

    out: list[list[float] | None] = [None] * len(texts)
    missing: list[int] = []
    for i, text in enumerate(texts):
        hit = cache.get(_cache_key(step, cfg, text)) if cache is not None else None
        if hit is not None:
            out[i] = hit["vector"]
        else:
            missing.append(i)

    if missing and real and cfg.max_model_calls is None:
        raise ModelConfigError(
            f"{step}: 진짜 임베딩 전송층을 부르는데 설정에 max_model_calls가 없음"
        )
    if missing and transport is None:
        if cfg.provider == "gemini":
            assert cfg.task_type is not None and cfg.dimensions is not None
            transport = GeminiEmbedTransport(task_type=cfg.task_type, dimensions=cfg.dimensions)
        else:
            transport = OpenAIEmbedTransport()

    def record(
        n_tokens: int,
        elapsed_ms: int,
        outcome: str,
        transport_try: int,
        invalid_kind: str | None = None,
    ) -> None:
        cost = (
            n_tokens * cfg.price_per_mtok_input / 1_000_000
            if cfg.price_per_mtok_input is not None and outcome != "cache_hit"
            else (0.0 if outcome == "cache_hit" else None)
        )
        ctx.recorder.record(
            CallRecord(
                run_id=ctx.run_id,
                step=step,
                model=cfg.model,
                input_tokens=n_tokens,
                output_tokens=0,
                cost=cost,
                elapsed_ms=elapsed_ms,
                from_cache=outcome == "cache_hit",
                attempt=1,
                outcome=outcome,
                transport_try=transport_try,
                invalid_kind=invalid_kind,
            )
        )

    if len(missing) < len(texts):
        record(0, 0, "cache_hit", 0)

    # 캐시에 없는 글만 묶음 크기대로 나눠 부른다
    for start in range(0, len(missing), cfg.batch_size):
        idx = missing[start : start + cfg.batch_size]
        batch = [texts[i] for i in idx]
        retries = cfg.max_retries or 0
        resp = None
        for n in range(retries + 1):
            try:
                ctx.budget.check(ctx.run_id, step, cfg.max_model_calls, cfg.max_input_tokens)
            except ModelCallLimitExceeded:
                record(0, 0, "limit_exceeded", n + 1)
                raise
            t0 = time.monotonic()
            try:
                resp = transport.embed(step=step, model=cfg.model, texts=batch)
            except RecordingMissing, ModelConfigError:
                raise  # 기록 없음·설정 잘못은 감싸지 않고 멈춘다
            except Exception as e:
                ctx.budget.add(ctx.run_id, step, 0)
                record(0, int((time.monotonic() - t0) * 1000), "transport_error", n + 1)
                if not (isinstance(e, TransportError) and e.retryable) or n == retries:
                    raise ModelCallFailed(f"{step}: {e} (시도 {n + 1}번)") from e
                sleep(2.0**n)
                continue
            ctx.budget.add(ctx.run_id, step, resp.input_tokens)
            # 개수가 다르면 어느 벡터가 어느 글인지 모른다: 조용히 넘기지 않는다
            if len(resp.vectors) != len(batch):
                record(resp.input_tokens, 0, "invalid_output", n + 1, "bad_value")
                raise ModelOutputInvalid(
                    f"{step}: 글 {len(batch)}개에 벡터 {len(resp.vectors)}개",
                    invalid_kind="bad_value",
                )
            # 캐시에 쓰기 전에 길이를 본다: 잘못된 벡터가 캐시에 남으면 다음 실행도 계속 실패한다
            lengths = {len(v) for v in resp.vectors} | {len(v) for v in out if v is not None}
            if len(lengths) != 1 or 0 in lengths:
                record(resp.input_tokens, 0, "invalid_output", n + 1, "bad_value")
                raise ModelOutputInvalid(
                    f"{step}: 벡터 길이가 서로 다르거나 0이다 {sorted(lengths)}",
                    invalid_kind="bad_value",
                )
            record(resp.input_tokens, int((time.monotonic() - t0) * 1000), "ok", n + 1)
            break
        for i, vector in zip(idx, resp.vectors, strict=True):
            out[i] = vector
            if cache is not None:
                cache.put(_cache_key(step, cfg, texts[i]), {"vector": vector})

    lengths = {len(v) for v in out}  # type: ignore[arg-type]
    if len(lengths) != 1 or 0 in lengths:
        # 모두 캐시 적중인데 캐시 안 벡터 길이가 섞인 경우
        raise ModelOutputInvalid(f"{step}: 벡터 길이가 서로 다르거나 0이다 {sorted(lengths)}")
    return out  # type: ignore[return-value]


def query_embedder(
    step: str, ctx: RunContext, config_dir: Path | None = None
) -> Callable[[str], list[float]]:
    """검색 계약의 Embed(글 하나 → 벡터)로 감싼다. retrieval은 이것을 받기만 한다."""

    def one(text: str) -> list[float]:
        return embed(step, [text], ctx=ctx, config_dir=config_dir)[0]

    return one
