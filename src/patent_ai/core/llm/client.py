"""모델 호출의 유일한 입구. 설정·프롬프트 파일을 거쳐 전송층을 부른다.

캐시는 cache 인자로 받는다(없으면 안 씀). 호출 상한·기록(task-3)은 이 함수 안에 나중에 끼운다.
"""

import json
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from patent_ai.core.llm.cache import Cache, make_cache_key
from patent_ai.core.llm.config import REPO_ROOT, load_step_config
from patent_ai.core.llm.errors import ModelOutputInvalid
from patent_ai.core.llm.prompts import render_prompt
from patent_ai.core.llm.transport import Transport, TransportResponse


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
    cache: Cache | None = None,
    config_dir: Path | None = None,
    root: Path | None = None,
) -> ModelResult:
    root = root or REPO_ROOT
    cfg = load_step_config(step, config_dir)
    prompt = render_prompt(cfg.prompt, variables, root)

    # 캐시 키: 프롬프트 파일 원문 해시 + 변수 + 설정 값 + attempt
    key = make_cache_key(
        model=cfg.model,
        prompt_template=(root / cfg.prompt).read_text(encoding="utf-8"),
        variables=variables,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
        attempt=attempt,
    )
    hit = cache.get(key) if cache is not None else None

    if hit is None and transport is None:
        from patent_ai.core.llm.transport import AnthropicTransport

        transport = AnthropicTransport()

    start = time.monotonic()
    if hit is not None:
        # 캐시 적중: 전송층을 부르지 않는다
        resp = TransportResponse(hit["text"], hit["input_tokens"], hit["output_tokens"])
    else:
        resp = transport.complete(
            step=step,
            model=cfg.model,
            prompt=prompt,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
        )
    elapsed_ms = int((time.monotonic() - start) * 1000)

    # 스키마가 있으면 답을 JSON으로 읽어 Pydantic 검사한다
    parsed = None
    if output_schema is not None:
        try:
            parsed = output_schema.model_validate(json.loads(resp.text))
        except json.JSONDecodeError as e:
            raise ModelOutputInvalid(f"답이 JSON이 아님: {e}") from e
        except ValidationError as e:
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

    # 가격 설정이 둘 다 있을 때만 비용을 계산한다
    cost = None
    if cfg.price_per_mtok_input is not None and cfg.price_per_mtok_output is not None:
        cost = (
            resp.input_tokens * cfg.price_per_mtok_input
            + resp.output_tokens * cfg.price_per_mtok_output
        ) / 1_000_000

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
