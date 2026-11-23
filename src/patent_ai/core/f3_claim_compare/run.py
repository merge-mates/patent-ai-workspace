"""F3 진입 함수: OA 정리 결과 + 사건 자료 + 설정(글자 입력 포함) -> F3Result.

순서: 청구항 나누기(거절이유 대상 청구항 + 그들이 인용하는 앞 청구항) -> 판단 단위 ->
(청구항 판이 확인되지 않았으면) 단위 낮추기 -> 대비 방식(설정 impl)으로 진보성·신규성 대비 ->
명확성 검토 -> 한 결과로 모으기. 대비 방식만 갈아 끼우고 나머지는 어느 방식이든 같다.
묶음(판단 단위) 하나의 모델 호출 실패는 그 묶음만 보류한다 (확인되지 않음 + 이유, #166 (가)).
청구항 나누기도 같다: 청구항 하나가 실패하면 그 청구항만 보류한다
(`f3_split:<oa_id>:claim<N>:call_failed`·`:limit_reached`, #317).
모든 묶음이 실패하면 단계 전체가 못 돈 것이라 예외로 올린다 (지휘가 실행 failed로 남긴다).
호출 상한에 닿은 묶음은 실패가 아니라 limit_reached로 보류하고 끝낸다 (ADR 0003 상한).
프로그래밍·설정 오류는 잡지 않는다.
"""

import logging

from patent_ai.core.bundle_errors import (
    BUNDLE_ERRORS,
    held_error_status,
    hold_for_error,
    is_dependent_skip,
    is_limit,
    raise_if_all_failed,
)
from patent_ai.core.f3_claim_compare.clarity import review_clarity_units
from patent_ai.core.f3_claim_compare.compare import (
    f3_query_embedder,
    make_searcher,
)
from patent_ai.core.f3_claim_compare.elements import SplitClaim, split_elements
from patent_ai.core.f3_claim_compare.inputs import F3Config
from patent_ai.core.f3_claim_compare.result import F3Result
from patent_ai.core.f3_claim_compare.strategies import get_strategy
from patent_ai.core.f3_claim_compare.units import build_units
from patent_ai.core.llm.limits import RunContext
from patent_ai.core.schemas.case_materials import CaseMaterials, HeldTask
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

_ALL_CHECKED = "판단 단위·대비표·명확성 검토가 모두 확인됨이고 보류한 작업이 없음"


def make_search_resources(config: F3Config, ctx: RunContext) -> tuple[Searcher, ChunkRepository]:
    """진짜 검색기와 조각 저장소를 만든다 (색인 DB는 DATABASE_URL, 질의 임베딩은 f3.embed 단계).

    테스트는 이 함수를 부르지 않고 run_f3에 메모리 저장소·가짜 임베딩 검색기를 넘긴다.
    """
    repo = PostgresChunkRepository.from_url()
    return make_searcher(config.settings, repo, f3_query_embedder(ctx)), repo


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
    tried = 0  # 모델을 부르러 간 청구항 수 (글자가 없어 보류한 것은 세지 않는다)
    errors: list[Exception] = []  # 상한이 아닌 호출 실패
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
        if claims[claim].strip():
            # 글자가 공백뿐이면 split_elements가 모델을 부르지 않으므로 분모에 넣지 않는다
            tried += 1
        try:
            split = split_elements(claim, claims[claim], numbers, ctx=ctx)
        except BUNDLE_ERRORS as e:
            # 청구항 하나의 호출 실패(다시 부른 답도 JSON·스키마가 틀림 / 전송 오류)는
            # 그 청구항만 보류한다 (#317, 묶음 규칙 #166 (가)와 같음). 그 청구항과 그를
            # 인용하는 대상 청구항은 인용 관계를 몰라 빠지지 않고 혼자 단위가 된다
            # (build_units: 확인되지 않음 + 직접 검토 필요. 독립항이 실패하면 종속항은
            # 부모 구성요소 없이 혼자 대비된다). 호출 상한은 실패가 아니라
            # limit_reached 보류다 (ADR 0003, 대비·명확성과 같음)
            held.append(hold_for_error("f3_split", f"{oa.oa_id}:claim{claim}", e))
            if not is_limit(e):
                errors.append(e)
            continue
        splits[claim] = split
        # 인용되는 앞 청구항도 나눠야 독립항 묶음과 함께 읽을 청구항을 알 수 있다
        todo |= set(split.depends_on or []) - seen
    raise_if_all_failed("run_f3 청구항 나누기", tried, errors)
    return splits, held


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

    # 1) 청구항 나누기 -> 2) 판단 단위 (어느 대비 방식이든 같은 공통 단계)
    splits, held = _split_claims(oa_result, config, ctx)
    units, unit_held = build_units(oa_result, splits)
    held += unit_held
    if config.inputs.claims_status.value != StatusValue.CONFIRMED:
        # OA 당시 청구항 판이 확인되지 않았으면 뒤 결과는 모두 input_unverified.
        # 대비 전에 낮춰야 대비표의 직접 검토 필요 표시가 이 상태를 본다
        units = [_unverified_unit(u) for u in units]

    # 3) 대비 방식(config/f3.yaml impl): 진보성·신규성 대비만 맡는다.
    #    검색기는 방식이 필요할 때만 만든다. 모르는 impl 이름이면 여기서 멈춘다
    strategy = get_strategy(config.settings.impl)

    def resources() -> tuple[Searcher, ChunkRepository]:
        if searcher is not None and repo is not None:
            return searcher, repo
        return make_search_resources(config, ctx)

    compared = strategy(units, oa_result, splits, config, ctx=ctx, resources=resources)

    # 4) 명확성 검토 (대비 방식과 따로)
    clarity = review_clarity_units(units, oa_result, config, ctx=ctx)

    # 모델을 부른 모든 묶음의 호출이 실패했다면 남은 결과가 없는 것: 단계 전체 실패다.
    # 부르기 전에 보류로 끝난 묶음(인용문헌 본문 없음 등)은 분모에서 뺀다.
    # 마지막 원래 예외를 그대로 올린다 (원인 종류가 바뀌지 않게)
    raise_if_all_failed(
        f"run_f3 {oa_id}",
        compared.units_tried + clarity.units_tried,
        [*compared.call_errors, *clarity.call_errors],
    )

    tables = compared.tables
    for h in compared.held_tasks + clarity.held_tasks:
        if all(h.task != old.task for old in held):
            held.append(h)
    statuses = (
        [u.status for u in units] + [t.status for t in tables] + [r.status for r in clarity.reviews]
    )
    # 보류한 작업이 있으면 그만큼 결과를 못 만든 것이다. 확인됨으로 모으지 않는다
    # (독립항에 차이점이 있어 종속항을 대비하지 않은 보류는 이유를 남길 뿐 status를 낮추지 않는다:
    #  기다리는 자료가 없는 정해진 건너뜀이다)
    statuses += [s for h in held if (s := _held_status(h, oa_id)) is not None]
    # 대비표·명확성 검토가 하나도 안 나온 단위도 마찬가지 (보류로 안 잡힌 경우까지)
    done = {t.unit_id for t in tables} | {r.unit_id for r in clarity.reviews}
    empty = [u.unit_id for u in units if u.unit_id not in done]
    if empty:
        logger.warning("run_f3 %s: 결과가 없는 판단 단위 %d개", oa_id, len(empty))
        missing = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
        statuses += [missing] * len(empty)
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


def _held_status(held: HeldTask, oa_id: str) -> Status | None:
    """보류한 작업 하나가 결과 전체 status에 주는 값.

    인용문헌 본문을 기다리는 보류(`f3_compare:<oa_id>:D2`)는 본문 미확보,
    그 밖(청구항 글자·대상 청구항·짚은 문구·대비할 구성요소가 없음)은 못 뽑음.
    """
    if is_dependent_skip(held.task):
        return None  # 독립항에 차이점이 있어 종속항을 대비하지 않음 (결과 status를 낮추지 않음)
    error_status = held_error_status(held.task)  # 모델 호출 실패·호출 상한 보류
    if error_status is not None:
        return error_status
    parts = held.task.split(":")
    waits_for_body = parts[:2] == ["f3_compare", oa_id] and (
        len(parts) == 3 or held.task.endswith(":spec")  # 진보성 단위의 명세서 보류도 본문 미확보
    )
    reason = UnverifiedReason.BODY_MISSING if waits_for_body else UnverifiedReason.NOT_EXTRACTED
    return Status(value=StatusValue.UNVERIFIED, reason=reason)


def _unverified_unit(unit: JudgmentUnit) -> JudgmentUnit:
    status = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.INPUT_UNVERIFIED)
    flags = list(dict.fromkeys([*unit.flags, Flag.NEEDS_HUMAN_REVIEW]))
    return unit.model_copy(update={"status": status, "flags": flags})
