"""서버가 켜질 때 끝나지 않은 실행을 정리한다 (이슈 #57).

실행은 서버 안 백그라운드 스레드에서 돈다. 서버가 꺼지면 그 스레드도 사라지므로
queued·running으로 남은 실행은 영영 안 끝난다. 조용히 두지 않고 실패와 이유를 남긴다.
waiting_for_human은 스레드가 필요 없는 상태라 그대로 둔다.
"""

import logging

from patent_ai.core.runs.state import InvalidRunTransition, RunError, RunState
from patent_ai.core.runs.store import RunNotFound, RunStatusStore

logger = logging.getLogger(__name__)

SERVER_RESTARTED = RunError(
    code="server_restarted",
    message="서버가 다시 켜져서 진행 중이던 실행이 중단되었다. 다시 실행해 주세요.",
)


def fail_unfinished_runs(store: RunStatusStore) -> list[str]:
    """queued·running 실행을 failed(server_restarted)로 바꾸고, 바꾼 run_id 목록을 돌려준다."""
    changed: list[str] = []
    for run_id in store.unfinished_run_ids():
        try:
            store.transition(run_id, RunState.FAILED, error=SERVER_RESTARTED)
        except InvalidRunTransition, RunNotFound:
            # 찾은 뒤 다른 쪽이 먼저 끝냈다: 먼저 쓴 쪽이 이긴다
            logger.info("재시작 정리: %s는 이미 바뀌어 건너뜀", run_id)
            continue
        changed.append(run_id)
    if changed:
        logger.warning("재시작으로 끝나지 않은 실행 %d건을 실패로 바꿈: %s", len(changed), changed)
    return changed
