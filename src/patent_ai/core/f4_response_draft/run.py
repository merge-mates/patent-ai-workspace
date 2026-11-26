"""F4 진입 함수: 방향 후보 → 의견서 초안 → 보정 청구항 초안 → 한데 묶기.

멈추지 않고 끝까지 돈다 (확신 낮은 묶음, 모델 호출이 실패한 묶음은 그 묶음만 보류).
사람을 기다릴지는 지휘가 정한다. 방향 후보 호출이 모델을 부른 모든 묶음에서 실패하면(아무것도
못 낸 것) 그 원래 예외를 올린다 (지휘가 실행을 failed로 끝낸다). 의견서·보정 실패는 늘 그 묶음 보류.
호출 상한에 닿은 묶음은 limit_reached로 보류하고 끝낸다.
"""

import logging

from patent_ai.core.f4_response_draft.amendment import (
    LEGALITY_NOTICE,
    AmendmentPart,
    assemble_drafts,
    build_amendments,
)
from patent_ai.core.f4_response_draft.config import F4Options, load_f4_options
from patent_ai.core.f4_response_draft.coverage import unchecked_rejections, uncovered
from patent_ai.core.f4_response_draft.directions import (
    RANK_NOTICE,
    amendment_limit_of,
    build_directions,
    unit_scope,
)
from patent_ai.core.f4_response_draft.inputs import F4Input
from patent_ai.core.f4_response_draft.opinion import build_opinion, planned_part
from patent_ai.core.f4_response_draft.opinion_v2 import build_opinion_v2
from patent_ai.core.f4_response_draft.result import F4Output
from patent_ai.core.llm.config import REPO_ROOT
from patent_ai.core.llm.errors import ModelConfigError
from patent_ai.core.llm.limits import RunContext
from patent_ai.core.schemas.common import Flag, worst_status
from patent_ai.core.schemas.direction import (
    AmendmentLimit,
    DirectionCandidates,
    DirectionSelection,
)
from patent_ai.core.schemas.oa_result import OAResult

logger = logging.getLogger(__name__)

ALL_F4_CHECKED = "방향 후보와 초안 모두 확인됨"
# 최후거절이유통지일 때 보정 프롬프트에 끼우는 제한 문구 (프롬프트라 파일로 둔다)
FINAL_LIMIT_PROMPT = "prompts/f4/amendment_limit_final.md"


def final_limit_note(oa: OAResult, options: F4Options) -> str:
    """보정 프롬프트에 끼울 제한 문구. 스위치가 켜져 있고 통지 종류가 최후일 때만 낸다.

    통지 종류를 모르면 넣지 않는다 (짐작으로 제한을 적용하지 않고, 방향 후보에서 확인을 요청한다).
    보정이 제한 안인지 밖인지는 코드가 판정하지 않는다.
    """
    if not options.final_rejection_limit:
        return ""
    if amendment_limit_of(oa).value != AmendmentLimit.FINAL:
        return ""
    path = REPO_ROOT / FINAL_LIMIT_PROMPT
    if not path.is_file():
        raise ModelConfigError(f"보정 제한 문구 파일이 없음: {path}")
    note = path.read_text(encoding="utf-8").strip()
    if not note:
        raise ModelConfigError(f"보정 제한 문구 파일이 비어 있음: {path}")
    return f"\n{note}\n"


def run_f4(inp: F4Input, *, ctx: RunContext, options: F4Options | None = None) -> F4Output:
    """OA 하나의 대응 방향 후보와 초안을 만든다. 모델 호출 순서는 방향 → 의견서 → 보정."""
    options = options or load_f4_options()
    directions = build_directions(inp, ctx, options=options)
    return _drafts_and_checks(inp, directions, ctx, options)


def redo_drafts(
    inp: F4Input,
    prev: F4Output,
    selections: dict[str, DirectionSelection],
    *,
    ctx: RunContext,
    options: F4Options | None = None,
) -> F4Output:
    """사람이 방향을 고른 뒤 초안만 다시 만든다 (#70). 방향 후보는 앞 실행(prev) 것을 그대로 쓴다.

    selections: 묶음(unit_id) -> 사람 선택. 없는 묶음은 앞 실행의 선택을 그대로 둔다.
    직접 쓴 방향(written_direction)은 AI가 초안을 만들지 않아 그 묶음은 보류로 남는다.
    의견서·보정은 OA 하나에 하나라 모든 묶음을 다시 잇는다 (바뀌지 않은 묶음은 같은 입력이라
    진짜 전송층에서는 모델 호출 캐시에 걸려 비용이 다시 들지 않는다).
    """
    options = options or load_f4_options()
    if prev.oa_id != inp.oa.oa_id:
        raise ValueError(f"앞 실행 결과의 OA({prev.oa_id})가 입력 OA({inp.oa.oa_id})와 다름")
    by_unit = {d.unit_id: d for d in prev.directions}
    unknown = sorted(set(selections) - set(by_unit))
    if unknown:
        raise ValueError(f"앞 실행에 방향 후보가 없는 묶음: {unknown}")
    directions = [
        # 다시 검사한다: 후보 밖 id·origin 어긋남은 DirectionCandidates가 거부한다
        DirectionCandidates.model_validate(
            {
                **d.model_dump(mode="json"),
                "selection": selections[d.unit_id].model_dump(mode="json"),
            }
        )
        if d.unit_id in selections
        else d
        for d in prev.directions
    ]
    return _drafts_and_checks(inp, directions, ctx, options)


def _drafts_and_checks(
    inp: F4Input, directions: list[DirectionCandidates], ctx: RunContext, options: F4Options
) -> F4Output:
    """방향 후보(고른 것 포함)로 의견서 → 보정 → 묶기, 그리고 누락·보류 검사."""
    oa_id = inp.oa.oa_id
    limit_note = final_limit_note(inp.oa, options)
    if not options.amendment_enabled:
        # 의견서만: 보정안 단계를 부르지 않고 바깥 보정 결과로 의견서를 쓴다 (11/26 P5)
        amendment = AmendmentPart(claims=[], statuses=[], held_units=[])
        opinion = build_opinion_v2(inp, directions, ctx)
    elif options.opinion_after_amendment:
        # 보정을 먼저 만들고, 의견서가 그 결과로 보정한 항을 설명한다 (실제 의견서처럼).
        # 보정 단계는 의견서의 based_on·held_units만 보므로 고른 후보로 미리 만든 값을 넘긴다
        amendment = build_amendments(
            inp,
            directions,
            planned_part(inp, directions),
            ctx,
            options=options,
            limit_note=limit_note,
        )
        opinion = build_opinion(inp, directions, ctx, options=options, amendment=amendment)
    else:
        opinion = build_opinion(inp, directions, ctx, options=options)
        amendment = build_amendments(
            inp, directions, opinion, ctx, options=options, limit_note=limit_note
        )
    # 모델 호출 실패·상한으로 보류한 묶음의 status: 같은 등급에 가려지지 않게 맨 앞에 둔다.
    # 실행 status와 초안 status가 같은 목록을 쓴다
    lead_statuses = [
        *[d.status for d in directions if not d.candidates and d.needs_recheck],
        *opinion.failed_statuses,
        *amendment.failed_statuses,
    ]
    drafts = assemble_drafts(oa_id, opinion, amendment, lead_statuses)

    # 보류한 묶음: 의견서 보류(확신 낮음) + 보정 보류(청구항 글자 없음 등), 묶음 순서 그대로
    held = [
        u.unit_id
        for u in sorted(inp.units, key=lambda u: (u.order, u.unit_id))
        if u.unit_id in opinion.held_units or u.unit_id in amendment.held_units
    ]
    if held:
        logger.warning("f4 %s: 초안을 보류한 묶음 %s", oa_id, held)

    flags: list[Flag] = []

    def flag(f: Flag) -> None:
        if f not in flags:
            flags.append(f)

    for inner in [*directions, *([drafts] if drafts else [])]:
        for f in inner.flags:
            flag(f)
    for f in [*opinion.flags, *amendment.flags]:  # 초안이 없어도(모두 보류) 표시는 남긴다
        flag(f)

    # 지원 안 하는 거절이유: status는 나쁘게 하지 않고 번호와 표시만 남긴다
    unsupported = [r.no for r in inp.oa.rejections if not r.supported]
    if unsupported:
        logger.warning(
            "f4 %s: AI가 다루지 않은 거절이유가 남아 있음 %s (직접 대응 필요)", oa_id, unsupported
        )
        flag(Flag.NEEDS_HUMAN_REVIEW)

    # 누락 검사: 모든 거절이유 × 모든 대상 청구항
    missing = uncovered(inp.oa, inp.units)
    if missing:
        logger.warning("f4 %s: 대응 누락 (거절이유, 청구항) %s", oa_id, missing)
        flag(Flag.NEEDS_HUMAN_REVIEW)

    # 대상 청구항을 못 읽은 거절이유는 누락을 셀 수 없다. 검사 못 했다는 사실을 결과에 남긴다
    unchecked = unchecked_rejections(inp.oa)
    if unchecked:
        flag(Flag.NEEDS_HUMAN_REVIEW)

    # 모델 호출 실패(호출 상한 포함)로 보류한 묶음의 이유를 맨 앞에 둔다 (초안이 없어도 남는다)
    statuses = list(lead_statuses)
    statuses += [d.status for d in directions] + ([drafts.status] if drafts else [])
    # 확인됨일 때의 글: 보류·누락이 있으면 "모두 확인됨"이라고 쓰지 않고 사실대로 적는다
    # (status 값은 원문 확인 여부만 뜻하고, 사람이 봐야 할 것은 flags와 아래 칸들로 드러낸다)
    notes: list[str] = []
    if held or missing or unchecked:
        notes.append(
            f"보류 {len(held)}묶음, 누락 쌍 {len(missing)}, "
            f"누락 검사 못 한 거절이유 {len(unchecked)}는 따로"
        )
    if unsupported:
        # 지원 안 하는 거절이유는 AI가 다루지 않았다: "모두 확인됨"으로 읽히지 않게 글로 드러낸다
        notes.append(f"AI가 다루지 않은 거절이유 {len(unsupported)}개(직접 대응 필요)")
    overlaps = amendment.overlaps
    if overlaps:
        # 겹침은 Drafts.flags로는 구분이 안 되므로(늘 붙어 있음) 글로 드러낸다
        nums = ", ".join(str(n) for n in sorted({o.claim for o in overlaps}))
        notes.append(
            f"같은 청구항을 여러 묶음이 고쳐 뒤 묶음 초안 {len(overlaps)}개를 싣지 않음"
            f"(청구항 {nums}, 직접 합치기 필요)"
        )
    checked = ALL_F4_CHECKED
    if notes:
        checked = f"만든 방향 후보·초안의 입력 확인됨 ({'; '.join(notes)})"
    return F4Output(
        checked_on=inp.checked_on,
        oa_id=oa_id,
        units=list(inp.units),
        directions=directions,
        drafts=drafts,
        held_units=held,
        unsupported_rejections=unsupported,
        uncovered=missing,
        coverage_unchecked=unchecked,
        amendment_overlaps=overlaps,
        amendment_scopes={u.unit_id: unit_scope(inp, u).widened for u in inp.units},
        amendment_limit_applied=bool(limit_note) and options.amendment_enabled,
        direction_amendment_mismatch=opinion.mismatch_units,
        rank_notice=RANK_NOTICE,
        legality_notice=LEGALITY_NOTICE,
        status=worst_status(statuses, checked),
        flags=flags,
    )
