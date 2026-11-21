"""결과 API가 보여 줄 것 고르기 (이슈 #191 T3). 라우터(api/results.py)는 이 함수만 부른다.

- 어느 실행을 보여 줄지: OA 정리(①)와 같은 실행. 그 OA에서 보여 줄 상태(succeeded·사람 기다림)인
  가장 최근 실행의 OA 정리를 먼저 찾고, 그 run_id로 F3·F4 결과를 읽는다. 그래서 결과 칸들이
  서로 다른 실행에서 섞이지 않는다. 그 실행이 없으면 None (API는 404 result_not_ready).
- 그 실행에 그 단계 결과가 없거나(넘김) 목록이 비면 빈 목록 + empty_reason. 이유 없이 비우지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from patent_ai.core.cases.results import OAResultStore
from patent_ai.core.cases.step_results import StepKind, StepResultStore
from patent_ai.core.f3_claim_compare.result import F3Result
from patent_ai.core.f4_response_draft.result import F4Output
from patent_ai.core.runs.state import RunState
from patent_ai.core.runs.store import RunStatusStore

ResultName = Literal[
    "units", "comparisons", "clarity-reviews", "legal-evidence", "directions", "drafts"
]

# 결과 이름 -> (그 결과를 내는 단계 도구, 저장한 단계, 결과에서 꺼낼 칸)
_SOURCES: dict[str, tuple[str, StepKind | None, str | None]] = {
    "units": ("run_f3", "f3", "units"),
    "comparisons": ("run_f3", "f3", "comparisons"),
    "clarity-reviews": ("run_f3", "f3", "clarity_reviews"),
    "legal-evidence": ("run_f2", None, None),  # F2는 아직 저장하는 결과가 없다
    "directions": ("run_f4", "f4", "directions"),
    "drafts": ("run_f4", "f4", "drafts"),
}

EMPTY_NONE_APPLIES = "해당 거절이유 없음"


@dataclass(frozen=True)
class ResultView:
    run_id: str
    value: Any  # 목록이면 list, drafts면 Drafts | None
    empty_reason: str | None  # 값이 비었을 때만
    step_result: F3Result | F4Output | None  # 알림 문구 등 결과 밖 칸이 필요할 때


def _why_missing(tool: str, run_id: str, runs: RunStatusStore) -> str:
    """그 실행에 단계 결과가 없는 이유."""
    for s in runs.skipped_steps(run_id):
        if s.step == tool:
            return f"넘김: {s.reason}"
    status = runs.get_status(run_id)
    if status is not None and status.state == RunState.WAITING_FOR_HUMAN:
        return f"보류: 사람 확인을 기다림 ({status.waiting_for})"
    return "확인되지 않음: 이 실행에 결과가 없음"


def result_view(
    oa_id: str,
    name: ResultName,
    *,
    oa_results: OAResultStore,
    step_results: StepResultStore,
    runs: RunStatusStore,
) -> ResultView | None:
    """보여 줄 실행이 없으면 None. 있으면 그 실행의 값과(비었으면) 이유."""
    saved = oa_results.latest_visible_oa_result(oa_id)
    if saved is None:
        return None
    run_id = saved.run_id
    tool, kind, field = _SOURCES[name]
    body = step_results.step_result(run_id, kind) if kind else None
    if body is None:
        empty = None if name == "drafts" else []
        return ResultView(run_id, empty, _why_missing(tool, run_id, runs), None)
    value = getattr(body, field)
    if value:
        return ResultView(run_id, value, None, body)
    if name == "drafts":
        # 모든 묶음을 보류해 초안이 없다 (사람이 방향을 고르거나 자료를 채우면 다시 만든다)
        return ResultView(run_id, None, "보류: 모든 묶음의 초안을 보류함", body)
    return ResultView(run_id, value, EMPTY_NONE_APPLIES, body)
