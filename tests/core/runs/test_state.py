"""실행 상태 전이 규칙 테스트. 기대값은 이슈 #57의 전이 표에서 가져왔다."""

import itertools

import pytest

from patent_ai.core.runs.state import (
    ACTIVE_STATES,
    FINISHED_STATES,
    InvalidRunTransition,
    RunError,
    RunState,
    check_transition,
)

Q, R, W = RunState.QUEUED, RunState.RUNNING, RunState.WAITING_FOR_HUMAN
S, F, C = RunState.SUCCEEDED, RunState.FAILED, RunState.CANCELLED

# 이슈의 허용 전이 표
ALLOWED = {
    Q: {R, C, F},
    R: {S, F, W, C},
    W: {R, C, F},
    S: set(),
    F: set(),
    C: set(),
}
ALLOWED_PAIRS = [(a, b) for a, bs in ALLOWED.items() for b in bs]
DENIED_PAIRS = [p for p in itertools.product(RunState, RunState) if p not in set(ALLOWED_PAIRS)]

ERR = RunError(code="model_error", message="모델 호출 실패")


def _extra(new):
    # 목적 상태가 요구하는 부가 정보를 채워 준다
    if new == F:
        return {"error": ERR}
    if new == W:
        return {"waiting_for": "방향 선택"}
    return {}


def test_상태_값은_DB_글자와_같다():
    assert {s.value for s in RunState} == {
        "queued",
        "running",
        "waiting_for_human",
        "succeeded",
        "failed",
        "cancelled",
    }


def test_끝난_상태와_진행_상태():
    assert FINISHED_STATES == {S, F, C}
    assert ACTIVE_STATES == {Q, R, W}


@pytest.mark.parametrize(("cur", "new"), ALLOWED_PAIRS)
def test_허용_전이는_통과(cur, new):
    check_transition(cur, new, **_extra(new))


@pytest.mark.parametrize(("cur", "new"), DENIED_PAIRS)
def test_표에_없는_전이는_거부(cur, new):
    with pytest.raises(InvalidRunTransition):
        check_transition(cur, new, **_extra(new))


def test_예외는_ValueError():
    assert issubclass(InvalidRunTransition, ValueError)


@pytest.mark.parametrize("cur", [Q, R, W])
def test_실패인데_error_없으면_거부(cur):
    with pytest.raises(InvalidRunTransition):
        check_transition(cur, F)


@pytest.mark.parametrize(
    "bad", [RunError(code="", message="x"), RunError(code="x", message=""), RunError("  ", "x")]
)
def test_error의_code나_message가_비면_거부(bad):
    with pytest.raises(InvalidRunTransition):
        check_transition(R, F, error=bad)


@pytest.mark.parametrize("waiting_for", [None, "", "   "])
def test_대기인데_waiting_for_없거나_빈_글자면_거부(waiting_for):
    with pytest.raises(InvalidRunTransition):
        check_transition(R, W, waiting_for=waiting_for)


def test_RunError_to_dict():
    assert ERR.to_dict() == {"code": "model_error", "message": "모델 호출 실패"}


def test_expected와_지금_상태가_다르면_거부한다():
    # 조건부 전이: "queued일 때만 cancelled로" 같은 요청 (취소와 시작이 겹칠 때)
    with pytest.raises(InvalidRunTransition):
        check_transition(RunState.RUNNING, RunState.CANCELLED, expected=RunState.QUEUED)


def test_expected와_지금_상태가_같으면_통과한다():
    check_transition(RunState.QUEUED, RunState.CANCELLED, expected=RunState.QUEUED)
