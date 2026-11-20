"""F3 대비 방식 고르기 (전략 패턴): 설정의 impl 이름 -> 구현.

방식 하나는 "OA 정리 결과 + 설정 -> 판단 단위와 대비표"까지를 맡는다. run_f3는 이 인터페이스만
부르고, 어느 방식인지는 config/f3.yaml의 impl이 정한다. 새 방식은 register_strategy로 이름만 더한다.
지금 방식은 split_search 하나: 청구항을 구성요소로 나누기 -> 구성요소마다 검색 -> 모델이 대비 판정.
명확성 검토는 대비 방식과 따로라 여기 들지 않는다 (run_f3가 한다).
"""

import logging
from collections.abc import Callable
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from patent_ai.core.f3_claim_compare.compare import CompareOutput, compare_units
from patent_ai.core.f3_claim_compare.elements import SplitClaim, split_elements
from patent_ai.core.f3_claim_compare.inputs import F3Config
from patent_ai.core.f3_claim_compare.units import build_units
from patent_ai.core.llm.errors import ModelConfigError
from patent_ai.core.llm.limits import RunContext
from patent_ai.core.schemas.case_materials import HeldTask
from patent_ai.core.schemas.judgment_unit import JudgmentUnit
from patent_ai.core.schemas.oa_result import OAResult, RejectionKind
from patent_ai.retrieval.contract import Searcher
from patent_ai.retrieval.repository import ChunkRepository

logger = logging.getLogger(__name__)

# 검색기와 조각 저장소를 필요할 때 만드는 함수 (대비할 단위가 없으면 부르지 않는다)
Resources = Callable[[], tuple[Searcher, ChunkRepository]]


class StrategyOutput(BaseModel):
    """대비 방식 하나가 돌려주는 것."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    units: list[JudgmentUnit] = Field(default_factory=list)  # 명확성 단위 포함
    splits: dict[int, SplitClaim] = Field(default_factory=dict)  # 청구항 번호 -> 나눈 결과
    compared: CompareOutput = Field(default_factory=CompareOutput)
    held_tasks: list[HeldTask] = Field(default_factory=list)  # 나누기·단위 만들기에서 보류한 것


class CompareStrategy(Protocol):
    def __call__(
        self, oa: OAResult, config: F3Config, *, ctx: RunContext, resources: Resources
    ) -> StrategyOutput: ...


# impl 이름 -> 구현
_REGISTRY: dict[str, CompareStrategy] = {}


def register_strategy(name: str) -> Callable[[CompareStrategy], CompareStrategy]:
    """대비 방식을 이름으로 등록하는 데코레이터."""

    def deco(fn: CompareStrategy) -> CompareStrategy:
        # 같은 이름에 다른 구현이 덮어쓰면 어느 방식이 도는지 알 수 없다. 막는다
        if name in _REGISTRY and _REGISTRY[name] is not fn:
            raise ValueError(f"impl {name!r}은 이미 등록돼 있다")
        _REGISTRY[name] = fn
        return fn

    return deco


def get_strategy(name: str) -> CompareStrategy:
    """설정의 impl 이름으로 대비 방식을 고른다. 모르는 이름은 설정 오류로 멈춘다."""
    if name not in _REGISTRY:
        raise ModelConfigError(
            f"config/f3.yaml의 impl {name!r}은 없는 대비 방식. 쓸 수 있는 이름: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name]


# ---- split_search: 나누기 -> 검색 -> 대비 ----
def _split_claims(
    oa: OAResult, config: F3Config, ctx: RunContext
) -> tuple[dict[int, SplitClaim], list[HeldTask]]:
    """거절이유 대상 청구항과, 그들이 인용하는 앞 청구항을 나눈다 (청구항마다 한 번)."""
    claims = config.inputs.claims_at_oa
    numbers = sorted(claims)
    todo: set[int] = set()
    for rej in oa.rejections:
        if rej.supported and rej.kind != RejectionKind.OTHER:
            todo |= set(rej.claims.value or [])
    splits: dict[int, SplitClaim] = {}
    held: list[HeldTask] = []
    seen: set[int] = set()
    while todo:
        claim = min(todo)  # 번호 순서대로 (같은 입력 -> 같은 호출 순서)
        todo.discard(claim)
        seen.add(claim)
        if claim not in claims:
            logger.warning("run_f3 %s: 청구항 %d의 글자가 없어 나누지 못함", oa.oa_id, claim)
            held.append(
                HeldTask(
                    task=f"f3_split:{oa.oa_id}:claim{claim}",
                    waiting_for=f"OA 당시 청구항 {claim} 글자",
                )
            )
            continue
        split = split_elements(claim, claims[claim], numbers, ctx=ctx)
        splits[claim] = split
        # 인용되는 앞 청구항도 나눠야 독립항 묶음과 함께 읽을 청구항을 알 수 있다
        todo |= set(split.depends_on or []) - seen
    return splits, held


@register_strategy("split_search")
def split_search(
    oa: OAResult, config: F3Config, *, ctx: RunContext, resources: Resources
) -> StrategyOutput:
    """지금 방식: 청구항을 구성요소로 나누고, 구성요소마다 검색해, 모델이 대비 판정한다."""
    splits, held = _split_claims(oa, config, ctx)
    units, unit_held = build_units(oa, splits)
    compared = CompareOutput()
    # 대비할 단위가 있을 때만 검색기를 만든다 (명확성뿐인 사건은 색인 DB를 열지 않는다)
    if any(u.rejection_kind != RejectionKind.CLARITY for u in units):
        searcher, repo = resources()
        compared = compare_units(units, oa, splits, config, ctx=ctx, searcher=searcher, repo=repo)
    return StrategyOutput(
        units=units, splits=splits, compared=compared, held_tasks=held + unit_held
    )
