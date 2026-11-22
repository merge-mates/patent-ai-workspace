"""사람이 답하는 것들의 판단 (이슈 #70 계획 ②). 라우터(api/human_inputs.py)는 이 함수들만 부른다.

- 번호 넣기: 실행이 출원번호·발송번호를 못 읽어 `waiting_for_human`이면, 사람이 넣은 번호를
  기록(human_inputs)에 남기고 그 실행을 이어 돌린다. 실행기는 그 실행이 저장한 OA 정리에 번호를
  덮어 `check_oa`부터 돈다 (체크포인터 없음, F1 모델 다시 안 부름).
- 정리 결과 "맞아요": 지금 보이는 OA 정리(그 run_id)를 사람이 확인했다고 남긴다.
사람이 넣은 번호는 OA 정리 칸에서 status 확인됨 + HUMAN_CHECKED 글로 AI가 읽은 값과 구분한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from patent_ai.core.cases.human_inputs import HumanInputStore, NumberKind
from patent_ai.core.cases.results import OAResultStore
from patent_ai.core.cases.start_run import OANotFoundError
from patent_ai.core.cases.store import CaseAppStore, CaseNotFoundError
from patent_ai.core.f1_oa_reader.rules import (
    normalize_application_number,
    normalize_dispatch_number,
)
from patent_ai.core.runs.state import InvalidRunTransition, RunState
from patent_ai.core.runs.store import RunStatusStore
from patent_ai.core.schemas.common import ExtractedValue, Status, StatusValue
from patent_ai.core.schemas.oa_result import _OA_FIELD_NAMES, OAResult, summarize_status

# 사람이 넣은 번호 칸의 확인 글 (원문에서 확인한 값이 아니라는 것을 드러낸다)
HUMAN_CHECKED = "사람이 직접 입력함 (원문 대조 아님)"

_NORMALIZE = {
    "application_number": normalize_application_number,
    "dispatch_number": normalize_dispatch_number,
}


class NotWaitingError(Exception):
    """그 번호를 기다리는 실행이 없다 (API는 409 not_waiting)."""


class InvalidNumberError(ValueError):
    """번호 꼴이 아니다 (API는 422 invalid_application_number / invalid_dispatch_number)."""


class ResultNotReadyError(LookupError):
    """확인할 OA 정리가 아직 없다 (API는 404 result_not_ready)."""


@dataclass(frozen=True)
class NumberEntered:
    case_id: str
    oa_id: str
    run_id: str  # 이어 도는 실행 (화면은 이것을 폴링)


@dataclass(frozen=True)
class Confirmation:
    oa_id: str
    run_id: str
    confirmed_at: datetime | None


def normalize_number(kind: NumberKind, text: str) -> str:
    """사람이 넣은 글자를 숫자만의 번호로. 글자 전체가 그 번호 꼴이 아니면 InvalidNumberError.

    앞뒤에 숫자·글자가 붙은 입력에서 번호 꼴 한 조각만 골라내지 않는다 (사람이 친 그대로만 받는다).
    """
    cleaned = text.strip().replace("-", "")
    found = _NORMALIZE[kind](text.strip())
    if not cleaned.isdigit() or found != cleaned:
        raise InvalidNumberError(kind)
    return found


def apply_human_numbers(oa: OAResult, numbers: dict[str, str]) -> OAResult:
    """저장한 OA 정리에 사람이 넣은 번호를 덮는다.

    칸의 글자(raw_text)도 사람 값으로 바꾸고 쪽은 비운다: 화면·의견서 입력이 raw_text를 먼저 읽어서,
    AI가 읽은 옛 글자를 남기면 사람 값 대신 그 글자가 "확인됨"으로 쓰인다 (리뷰 막음).
    AI가 읽은 원래 글자는 그 실행의 첫 OA 정리 줄에 남아 있다.
    """
    update = {}
    for kind, value in numbers.items():
        update[kind] = ExtractedValue[str](
            value=value,
            raw_text=value,
            page=None,
            status=Status(value=StatusValue.CONFIRMED, checked=HUMAN_CHECKED),
        )
    # 결과 전체 status는 칸을 모은 값이라 번호를 바꾸면 다시 모은다
    fields = {k: update.get(k, getattr(oa, k)) for k in _OA_FIELD_NAMES}
    data = {**oa.model_dump(mode="json"), **update, "status": summarize_status(**fields)}
    # 다시 검사한다 (만든 뒤 칸을 몰래 바꾸지 않게 model_copy 대신 model_validate)
    return OAResult.model_validate(data)


def _take_waiting(oa_id: str, run_id: str, kind: NumberKind, number: str, runs, human) -> None:
    """기다리던 실행을 waiting → queued로 조건부 전이한 뒤에만 번호를 남긴다 (#269 리뷰 막음).

    전이에 지면(이미 다른 PATCH가 가져감·취소됨) 번호를 남기지 않고 NotWaitingError (409).
    그래서 실행기가 잡기 전에 두 번째 PATCH가 와도 나중 번호가 몰래 이기지 않고, 상태도 바로
    queued로 보여 화면이 다시 폴링한다.
    """
    try:
        runs.transition(run_id, RunState.QUEUED, expected=RunState.WAITING_FOR_HUMAN)
    except InvalidRunTransition:
        raise NotWaitingError(run_id) from None
    human.add(oa_id, run_id, kind, number)


def _waiting_run(oa, runs: RunStatusStore, kind: NumberKind) -> str | None:
    """그 OA의 가장 최근 실행이 이 번호를 기다리면 그 run_id."""
    run = oa.latest_run if oa else None
    if run is None:
        return None
    status = runs.get_status(run.id)
    if status is None or status.state != RunState.WAITING_FOR_HUMAN or status.waiting_for != kind:
        return None
    return run.id


def enter_application_number(
    case_id: str,
    text: str,
    *,
    store: CaseAppStore,
    runs: RunStatusStore,
    human: HumanInputStore,
) -> NumberEntered:
    case = store.get_case(case_id)
    if case is None:
        raise CaseNotFoundError(case_id)
    number = normalize_number("application_number", text)
    for ref in reversed(case.oas):  # 가장 늦게 올린 OA부터
        run_id = _waiting_run(store.get_oa(ref.oa_id), runs, "application_number")
        if run_id is not None:
            _take_waiting(ref.oa_id, run_id, "application_number", number, runs, human)
            return NumberEntered(case_id, ref.oa_id, run_id)
    raise NotWaitingError(case_id)


def enter_dispatch_number(
    oa_id: str,
    text: str,
    *,
    store: CaseAppStore,
    runs: RunStatusStore,
    human: HumanInputStore,
) -> NumberEntered:
    oa = store.get_oa(oa_id)
    if oa is None:
        raise OANotFoundError(oa_id)
    number = normalize_number("dispatch_number", text)
    run_id = _waiting_run(oa, runs, "dispatch_number")
    if run_id is None:
        raise NotWaitingError(oa_id)
    _take_waiting(oa_id, run_id, "dispatch_number", number, runs, human)
    return NumberEntered(oa.case_id, oa_id, run_id)


def _visible_run(oa_id: str, store: CaseAppStore, oa_results: OAResultStore) -> str:
    if store.get_oa(oa_id) is None:
        raise OANotFoundError(oa_id)
    saved = oa_results.latest_visible_oa_result(oa_id)
    if saved is None:
        raise ResultNotReadyError(oa_id)
    return saved.run_id


def confirm_oa_result(
    oa_id: str, *, store: CaseAppStore, oa_results: OAResultStore, human: HumanInputStore
) -> Confirmation:
    """지금 보이는 OA 정리를 사람이 확인했다 ("맞아요")."""
    run_id = _visible_run(oa_id, store, oa_results)
    at = human.add(oa_id, run_id, "oa_result_confirmed", None)
    return Confirmation(oa_id, run_id, at)


def oa_result_confirmation(
    oa_id: str, *, store: CaseAppStore, oa_results: OAResultStore, human: HumanInputStore
) -> Confirmation:
    """지금 보이는 OA 정리의 확인 여부. 다른 실행의 정리를 확인했던 것은 세지 않는다."""
    run_id = _visible_run(oa_id, store, oa_results)
    return Confirmation(oa_id, run_id, human.confirmed_at(oa_id, run_id))
