"""OA에 실행을 새로 만드는 판단 (이슈 #57). 라우터는 이 함수를 부르기만 한다.

같은 OA에 진행 중(queued·running·waiting_for_human) 실행이 있으면 새로 만들지 않는다.
(동시에 두 요청이 오면 둘 다 통과할 수 있는 것은 알려진 한계. 한 사람이 쓰는 앱이라 둔다.)
"""

from patent_ai.core.cases.store import CaseAppStore, RunRow
from patent_ai.core.runs.state import ACTIVE_STATES, RunState


class OANotFoundError(LookupError):
    """없는 OA (API는 404 oa_not_found)."""


class RunInProgressError(Exception):
    """같은 OA에 진행 중인 실행이 있다 (API는 409 run_in_progress)."""


def has_active_run(latest_state: str | None) -> bool:
    """가장 최근 실행의 상태가 진행 중이면 True. 실행이 없으면(None) False."""
    return latest_state is not None and RunState(latest_state) in ACTIVE_STATES


def create_run_for_oa(store: CaseAppStore, oa_id: str) -> RunRow:
    oa = store.get_oa(oa_id)
    if oa is None:
        raise OANotFoundError(oa_id)
    if has_active_run(oa.latest_run.state if oa.latest_run else None):
        raise RunInProgressError(oa_id)
    return store.create_run(oa_id)
