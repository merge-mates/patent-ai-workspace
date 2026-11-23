"""F2·F3·F4 결과 저장·다시 읽기 (이슈 #191 T2, F2는 #28). Postgres 구현은 `step_results_pg.py`.

- 실행 하나에 단계(f2·f3·f4)마다 한 줄. 본문은 도구 출력 그대로(F2Result·F3Result·F4Output)라
  다시 읽으면 같은 객체가 나온다.
- 어느 실행을 보여 줄지는 여기서 고르지 않는다: 결과 API가 OA 정리(oa_results)와 같은 실행을
  골라 run_id로 읽는다. 그래야 화면의 결과 칸들이 서로 다른 실행에서 섞이지 않는다.
"""

from __future__ import annotations

import threading
from typing import Literal, Protocol

from patent_ai.core.f2_legal_research.run import F2Result
from patent_ai.core.f3_claim_compare.result import F3Result
from patent_ai.core.f4_response_draft.result import F4Output
from patent_ai.db.ids import new_id

StepKind = Literal["f2", "f3", "f4"]
StepBody = F2Result | F3Result | F4Output

_MODELS: dict[str, type[StepBody]] = {"f2": F2Result, "f3": F3Result, "f4": F4Output}


def kind_of(body: StepBody) -> StepKind:
    """결과 객체가 어느 단계 것인지. 모르는 객체면 TypeError (조용히 다른 칸에 넣지 않는다)."""
    if isinstance(body, F2Result):
        return "f2"
    if isinstance(body, F3Result):
        return "f3"
    if isinstance(body, F4Output):
        return "f4"
    raise TypeError(f"F2·F3·F4 결과가 아님: {type(body).__name__}")


def parse_body(kind: StepKind, data: dict) -> StepBody:
    """저장한 jsonb를 단계별 모델로 되살린다."""
    return _MODELS[kind].model_validate(data)


class StepResultStore(Protocol):
    def save_step_result(self, oa_id: str, run_id: str, body: StepBody) -> str:
        """저장한 줄의 ID를 돌려준다. 같은 실행·같은 단계를 두 번 저장하면 예외 (단계마다 하나)."""
        ...

    def step_result(self, run_id: str, kind: StepKind) -> StepBody | None:
        """그 실행이 낸 단계 결과. 그 단계를 넘겼거나 실패했으면 None."""
        ...


class DuplicateStepResult(ValueError):
    """같은 실행·같은 단계 결과가 이미 있다."""


class InMemoryStepResultStore:
    """테스트용. 저장할 때 json으로 한 번 바꿔 두어 Postgres와 같은 왕복을 거친다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[tuple[str, str], tuple[str, dict]] = {}  # (run, kind) -> (oa, 본문)

    def save_step_result(self, oa_id: str, run_id: str, body: StepBody) -> str:
        kind = kind_of(body)
        with self._lock:
            if (run_id, kind) in self._rows:
                raise DuplicateStepResult(f"{run_id}/{kind}")
            self._rows[(run_id, kind)] = (oa_id, body.model_dump(mode="json"))
        return new_id("sres")  # Postgres 표와 같은 모양의 ID

    def step_result(self, run_id: str, kind: StepKind) -> StepBody | None:
        with self._lock:
            row = self._rows.get((run_id, kind))
        return parse_body(kind, row[1]) if row else None
