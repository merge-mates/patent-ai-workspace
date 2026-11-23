"""사건 전체 검사 (이슈 #304 T2). 라우터(api/drafts.py)는 case_check()만 부른다.

GET /oas/{oa_id}/case-check: 지금 보이는 실행(OA 정리와 같은 실행)의 저장된 결과로 검사한다.
- 응답 모양은 화면 임시 타입 `CaseCheck`(web/src/types/provisional/pending.ts)에 맞춘다.
  결과 칸은 F4 설계 질문(#39)이라, 정해지면 결과 스키마(core/schemas/)로 올린다.
- 지금 검사하는 것: 지원 안 하는 거절이유(OA 정리), 두 묶음이 같은 청구항을 고친 것(F4).
- 아직 검사하지 않는 규칙은 "ok"로 지어내지 않고 warn + "확인되지 않음"으로 보인다
  (검사 안 함 ≠ 문제 없음).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from patent_ai.core.cases.result_views import result_view
from patent_ai.core.cases.results import OAResultStore
from patent_ai.core.cases.step_results import StepResultStore
from patent_ai.core.f4_response_draft.result import F4Output
from patent_ai.core.runs.store import RunStatusStore

UNSUPPORTED = "지원 안 하는 거절이유"
OVERLAPS = "같은 청구항을 고친 묶음"
# product.md 5절 F4 7번 규칙 중 아직 코드가 없는 것 (#39)
NOT_CHECKED = ("독립항 보정이 종속항에 번짐", "삭제 뒤 인용 번호", '"또는"형 종속항 가지')
NOT_CHECKED_DETAIL = "확인되지 않음: 아직 검사하지 않는 규칙 (직접 확인 필요)"


class CaseCheckItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str  # 검사 규칙
    result: Literal["ok", "warn", "fail"]
    detail: str


class CaseCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    oa_id: str
    run_id: str  # 검사한 실행 (OA 정리와 같은 실행)
    items: list[CaseCheckItem]
    unsupported_rejections: list[int]  # AI가 다루지 않은 거절이유 번호 (직접 대응 필요)


def case_check(
    oa_id: str,
    *,
    oa_results: OAResultStore,
    step_results: StepResultStore,
    runs: RunStatusStore,
) -> CaseCheck | None:
    """보여 줄 실행이 없으면 None (API는 404 result_not_ready)."""
    saved = oa_results.latest_visible_oa_result(oa_id)
    if saved is None:
        return None
    # 지원 안 하는 거절이유는 OA 정리에서 바로 센다 (F4를 넘겨도 알 수 있다)
    unsupported = [r.no for r in saved.result.rejections if not r.supported]
    if unsupported:
        nums = ", ".join(str(n) for n in unsupported)
        first = CaseCheckItem(
            name=UNSUPPORTED,
            result="warn",
            detail=f"거절이유 {nums}번은 AI가 다루지 않음 (직접 대응 필요)",
        )
    else:
        first = CaseCheckItem(name=UNSUPPORTED, result="ok", detail="모든 거절이유를 AI가 다룸")

    items = [first, _overlaps(oa_id, oa_results, step_results, runs)]
    items += [CaseCheckItem(name=n, result="warn", detail=NOT_CHECKED_DETAIL) for n in NOT_CHECKED]
    return CaseCheck(
        oa_id=oa_id, run_id=saved.run_id, items=items, unsupported_rejections=unsupported
    )


def _overlaps(oa_id, oa_results, step_results, runs) -> CaseCheckItem:
    """두 묶음이 같은 청구항을 고쳐 뒤 묶음 초안을 싣지 않은 곳 (F4 amendment_overlaps)."""
    view = result_view(oa_id, "drafts", oa_results=oa_results, step_results=step_results, runs=runs)
    f4 = view.step_result if view and isinstance(view.step_result, F4Output) else None
    if f4 is None:
        # F4를 넘겼거나 못 읽었다: 겹침이 없다고 하지 않는다
        why = view.empty_reason if view else None
        return CaseCheckItem(
            name=OVERLAPS, result="warn", detail=f"확인되지 않음: 대응 초안 결과 없음 ({why})"
        )
    if not f4.amendment_overlaps:
        return CaseCheckItem(name=OVERLAPS, result="ok", detail="두 묶음이 함께 고친 청구항 없음")
    parts = [
        f"청구항 {o.claim}: {o.kept_unit} 초안만 싣고 {o.dropped_unit} 초안은 빠짐"
        for o in f4.amendment_overlaps
    ]
    return CaseCheckItem(
        name=OVERLAPS, result="warn", detail="; ".join(parts) + " (직접 합쳐야 함)"
    )
