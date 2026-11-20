"""F3 진입 함수: OA 정리 결과 + 사건 자료 + 설정(글자 입력 포함) -> F3Result.

순서: 대비 방식(설정 impl. 지금은 청구항 나누기 -> 판단 단위 -> 진보성·신규성 대비) ->
명확성 검토 -> 한 결과로 모으기.
단계가 예외로 실패하면 삼키지 않는다 (지휘가 실행 failed로 남긴다).
"""

import logging

from patent_ai.core.f3_claim_compare.clarity import review_clarity_units
from patent_ai.core.f3_claim_compare.compare import (
    f3_query_embedder,
    make_searcher,
)
from patent_ai.core.f3_claim_compare.inputs import F3Config
from patent_ai.core.f3_claim_compare.result import F3Result
from patent_ai.core.f3_claim_compare.strategies import get_strategy
from patent_ai.core.llm.limits import RunContext
from patent_ai.core.schemas.case_materials import CaseMaterials
from patent_ai.core.schemas.common import (
    Flag,
    Status,
    StatusValue,
    UnverifiedReason,
    worst_status,
)
from patent_ai.core.schemas.judgment_unit import JudgmentUnit
from patent_ai.core.schemas.oa_result import OAResult, RejectionKind
from patent_ai.retrieval.contract import Searcher
from patent_ai.retrieval.repository import ChunkRepository, PostgresChunkRepository

logger = logging.getLogger(__name__)

_ALL_CHECKED = "판단 단위·대비표·명확성 검토의 status가 모두 확인됨"


def make_search_resources(config: F3Config, ctx: RunContext) -> tuple[Searcher, ChunkRepository]:
    """진짜 검색기와 조각 저장소를 만든다 (색인 DB는 DATABASE_URL, 질의 임베딩은 f3.embed 단계).

    테스트는 이 함수를 부르지 않고 run_f3에 메모리 저장소·가짜 임베딩 검색기를 넘긴다.
    """
    repo = PostgresChunkRepository.from_url()
    return make_searcher(config.settings, repo, f3_query_embedder(ctx)), repo


def run_f3(
    oa_result: OAResult,
    case_materials: CaseMaterials,
    config: F3Config,
    *,
    ctx: RunContext,
    searcher: Searcher | None = None,
    repo: ChunkRepository | None = None,
) -> F3Result:
    """F3 한 바퀴. searcher·repo를 안 주면 진짜 것(색인 DB + 질의 임베딩)을 만든다.

    searcher·repo는 데이터가 아니라 객체라 설정 모델에 싣지 않고 따로 받는다.
    """
    if (searcher is None) != (repo is None):
        raise ValueError("searcher와 repo는 같이 주거나 같이 비운다 (repo 없이 searcher만은 안 됨)")
    oa_id = oa_result.oa_id
    known = {d.document_id for d in case_materials.documents}
    if known and config.inputs.claims_document_id not in known:
        logger.warning(
            "run_f3 %s: 청구항 문서 %s가 사건 자료 목록에 없음",
            oa_id,
            config.inputs.claims_document_id,
        )
    for rej in oa_result.rejections:
        if not rej.supported or rej.kind == RejectionKind.OTHER:
            # 지원 안 하는 거절이유는 단위를 만들지 않는다 (OA 결과의 flags로 사람에게 보인다)
            logger.warning(
                "run_f3 %s: 거절이유 %d는 지원 안 함 (단위를 만들지 않음)", oa_id, rej.no
            )

    # 1) 대비 방식(config/f3.yaml impl): 청구항 나누기 -> 판단 단위 -> 진보성·신규성 대비.
    #    검색기는 방식이 필요할 때만 만든다. 모르는 impl 이름이면 여기서 멈춘다
    strategy = get_strategy(config.settings.impl)

    def resources() -> tuple[Searcher, ChunkRepository]:
        if searcher is not None and repo is not None:
            return searcher, repo
        return make_search_resources(config, ctx)

    out = strategy(oa_result, config, ctx=ctx, resources=resources)
    units, compared = out.units, out.compared
    held = list(out.held_tasks)
    input_ok = config.inputs.claims_status.value == StatusValue.CONFIRMED
    if not input_ok:
        # OA 당시 청구항 판이 확인되지 않았으면 뒤 결과는 모두 input_unverified
        units = [_unverified_unit(u) for u in units]

    # 2) 명확성 검토 (대비 방식과 따로)
    clarity = review_clarity_units(units, oa_result, config, ctx=ctx)

    tables = compared.tables
    for h in compared.held_tasks + clarity.held_tasks:
        if all(h.task != old.task for old in held):
            held.append(h)
    statuses = (
        [u.status for u in units] + [t.status for t in tables] + [r.status for r in clarity.reviews]
    )
    if not statuses:
        logger.warning("run_f3 %s: 판단 단위·대비표·명확성 검토가 모두 0개", oa_id)
    return F3Result(
        oa_id=oa_id,
        units=units,
        comparisons=tables,
        clarity_reviews=clarity.reviews,
        held_tasks=held,
        search_log=compared.search_log,
        examiner_locations=compared.examiner_locations,
        status=worst_status(statuses, _ALL_CHECKED),
    )


def _unverified_unit(unit: JudgmentUnit) -> JudgmentUnit:
    status = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.INPUT_UNVERIFIED)
    flags = list(dict.fromkeys([*unit.flags, Flag.NEEDS_HUMAN_REVIEW]))
    return unit.model_copy(update={"status": status, "flags": flags})
