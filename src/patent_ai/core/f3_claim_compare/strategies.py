"""F3 대비 방식 고르기 (전략 패턴): 설정의 impl 이름 -> 구현.

방식 하나는 "판단 단위 + 나눈 청구항 -> 진보성·신규성 대비표"만 맡는다.
청구항 나누기, 판단 단위 만들기, 입력 상태에 따른 단위 낮추기, 명확성 검토는 어느 방식이든
같아야 해서 run_f3의 공통 단계다 (방식이 빠뜨릴 수 없게).
어느 방식인지는 config/f3.yaml의 impl이 정한다. 새 방식은 register_strategy로 이름만 더한다.
지금 방식은 split_search 하나: 구성요소마다 검색 -> 모델이 대비 판정.
"""

import logging
from collections.abc import Callable, Mapping
from typing import Protocol

from patent_ai.core.f3_claim_compare.compare import CompareOutput, compare_units
from patent_ai.core.f3_claim_compare.elements import SplitClaim
from patent_ai.core.f3_claim_compare.inputs import F3Config
from patent_ai.core.llm.errors import ModelConfigError
from patent_ai.core.llm.limits import RunContext
from patent_ai.core.schemas.judgment_unit import JudgmentUnit
from patent_ai.core.schemas.oa_result import OAResult, RejectionKind
from patent_ai.retrieval.contract import Searcher
from patent_ai.retrieval.repository import ChunkRepository

logger = logging.getLogger(__name__)

# 검색기와 조각 저장소를 필요할 때 만드는 함수 (대비할 단위가 없으면 부르지 않는다)
Resources = Callable[[], tuple[Searcher, ChunkRepository]]


class CompareStrategy(Protocol):
    """대비 방식이 지킬 약속 (run_f3가 믿고 쓴다).

    묶음(판단 단위)마다 모델 호출 예외(`BUNDLE_ERRORS`)를 잡아 그 묶음만 보류하고,
    `CompareOutput.units_tried`(모델 호출까지 간 묶음 수, 부르기 전에 보류된 묶음은 뺌)와
    `call_errors`(호출 실패의 원래 예외, 호출 상한은 제외)를 채운다.
    그래야 run_f3가 "모든 묶음 실패"를 가르고 원래 예외를 올린다.
    `compare_units`를 쓰면 이 약속이 지켜진다.
    """

    def __call__(
        self,
        units: list[JudgmentUnit],
        oa: OAResult,
        splits: Mapping[int, SplitClaim],
        config: F3Config,
        *,
        ctx: RunContext,
        resources: Resources,
    ) -> CompareOutput: ...


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


@register_strategy("split_search")
def split_search(
    units: list[JudgmentUnit],
    oa: OAResult,
    splits: Mapping[int, SplitClaim],
    config: F3Config,
    *,
    ctx: RunContext,
    resources: Resources,
) -> CompareOutput:
    """지금 방식: 나눈 구성요소마다 인용문헌 안을 검색하고, 모델이 대비 판정한다."""
    # 대비할 단위가 있을 때만 검색기를 만든다 (명확성뿐인 사건은 색인 DB를 열지 않는다)
    if not any(u.rejection_kind != RejectionKind.CLARITY for u in units):
        return CompareOutput()
    searcher, repo = resources()
    return compare_units(units, oa, splits, config, ctx=ctx, searcher=searcher, repo=repo)
