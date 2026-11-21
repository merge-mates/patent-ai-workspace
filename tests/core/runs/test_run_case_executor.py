"""run_case 실행기 (이슈 #191 T1). 확인: uv run pytest tests/core/runs -k run_case

#180 한 바퀴(F1 → F3 → F2 넘김 → F4)를 기록된 응답으로 돌리고, 실행 상태·결과 저장을 본다.
네트워크·키·DB 없음.
"""

import threading

import pytest

from patent_ai.core.agents.orchestrator import CaseInput
from patent_ai.core.cases.results import InMemoryOAResultStore
from patent_ai.core.cases.run_inputs import RunInputNotFound
from patent_ai.core.cases.step_results import InMemoryStepResultStore
from patent_ai.core.runs.cancel import CancelRegistry, request_cancel
from patent_ai.core.runs.run_case_executor import RunCaseExecutor
from patent_ai.core.runs.state import RunState
from patent_ai.core.schemas.common import Status, StatusValue, UnverifiedReason
from tests.core.run_case_fakes import (
    CHECKED_ON,
    fake_ctx,
    real_config,
    texts,
    wire,
    wire_broken_pdf,
)
from tests.core.runs.fake_executor import MemoryStatusStore

RID, OID = "r_1", "oa_1"


class _Cases:
    """지휘의 사건 찾기: 기본은 새 사건. found를 주면 같은 OA가 이미 있다."""

    def __init__(self, found=None):
        self.found = found

    def find_oa(self, application_number, dispatch_number):
        return self.found

    def find_case(self, application_number):
        return None


class _Inputs:
    def __init__(self, tmp_path, with_texts=True, gate: threading.Event | None = None):
        self.tmp_path = tmp_path
        self.with_texts = with_texts
        self.gate = gate  # 주면 이 표시가 설 때까지 입력 만들기에서 멈춘다 (한 번에 하나 확인용)
        self.called: list[str] = []

    def case_input(self, oa_id):
        self.called.append(oa_id)
        if self.gate is not None:
            assert self.gate.wait(5)
        if oa_id == "없음":
            raise RunInputNotFound(oa_id)
        return CaseInput(
            case_id="c_1",
            oa_document=self.tmp_path / "oa.pdf",
            oa_document_id="d_1",
            texts=texts() if self.with_texts else None,
        )


class Env:
    def __init__(self, tmp_path, *, with_texts=True, cases=None, store=None):
        self.store = store or MemoryStatusStore()
        self.registry = CancelRegistry()
        self.oa_results = InMemoryOAResultStore(self.store)
        self.step_results = InMemoryStepResultStore()
        self.inputs = _Inputs(tmp_path, with_texts)
        self.lock = threading.Lock()
        self.executor = RunCaseExecutor(
            store=self.store,
            registry=self.registry,
            oa_results=self.oa_results,
            step_results=self.step_results,
            inputs=self.inputs,
            cases=cases or _Cases(),
            config_path=real_config(tmp_path),
            make_ctx=fake_ctx,
            today=lambda: CHECKED_ON,
            lock=self.lock,
        )

    def run(self, run_id=RID, oa_id=OID):
        if run_id not in self.store.runs:
            self.store.add(run_id, oa_id)
        self.executor.execute(run_id, oa_id)
        return self.store.get_status(run_id)


@pytest.fixture
def env(tmp_path, monkeypatch):
    wire(monkeypatch)
    return Env(tmp_path)


def test_run_case_한_바퀴가_끝나면_succeeded이고_F1_F3_F4_결과가_저장된다(env):
    st = env.run()
    assert st.state == RunState.SUCCEEDED and st.error is None
    assert [(oa, run) for oa, run, _ in env.oa_results.saved] == [(OID, RID)]
    f3, f4 = env.step_results.step_result(RID, "f3"), env.step_results.step_result(RID, "f4")
    assert f3 is not None and f3.units and f3.comparisons
    assert f4 is not None and f4.directions
    # F2는 넘긴 단계로 실행 상태에 남는다 (outcome skipped 줄이 그대로 옮겨짐)
    skipped = env.store.skipped_steps(RID)
    assert [s.step for s in skipped] == ["run_f2"] and "tool_missing" in skipped[0].reason


def test_run_case_지금_하는_일이_단계마다_바뀐다(env):
    env.run()
    assert env.store.step_history[RID] == [
        "OA 정리 중",
        "OA 시점까지 자료 자르는 중",
        "청구항–인용문헌 대비 중",
        "법률 근거 조사 중",
        "대응 방향·초안 만드는 중",
        "결과 저장 중",
    ]


def test_run_case_확인_기준일은_실행기가_넣은_날이다(env):
    env.run()
    f4 = env.step_results.step_result(RID, "f4")
    assert f4 is not None  # checked_on이 없으면 F4는 넘겨진다
    assert env.inputs.called == [OID]


def test_run_case_청구항_글자가_없으면_F3_F4는_넘긴_이유가_남고_결과가_없다(tmp_path, monkeypatch):
    wire(monkeypatch)
    env = Env(tmp_path, with_texts=False)
    st = env.run()
    # 실행 자체는 끝난다. 하지만 F3·F4가 성공한 것처럼 보이지 않는다
    assert st.state == RunState.SUCCEEDED
    assert env.step_results.step_result(RID, "f3") is None
    assert env.step_results.step_result(RID, "f4") is None
    skipped = {s.step: s.reason for s in env.store.skipped_steps(RID)}
    assert set(skipped) == {"run_f3", "run_f2", "run_f4"}
    assert skipped["run_f3"].startswith("input_unverified")
    assert skipped["run_f4"].startswith("input_unverified")


def test_run_case_단계가_실패하면_failed이고_예외_원문은_이유에_없다(tmp_path, monkeypatch):
    wire(monkeypatch)
    wire_broken_pdf(monkeypatch, secret="비밀 원문 문장")
    env = Env(tmp_path)
    st = env.run()
    assert st.state == RunState.FAILED
    assert st.error["code"] == "step_failed"
    assert "extract_pages" in st.error["message"] and "PdfReadError" in st.error["message"]
    assert "비밀 원문 문장" not in st.error["message"]
    assert env.oa_results.saved == []
    assert env.step_results.step_result(RID, "f3") is None


def test_run_case_이미_있는_OA면_failed_oa_already_exists(tmp_path, monkeypatch):
    wire(monkeypatch)
    env = Env(tmp_path, cases=_Cases(found=("c_옛", "oa_옛")))
    st = env.run()
    assert st.state == RunState.FAILED
    assert st.error["code"] == "oa_already_exists" and "oa_옛" in st.error["message"]
    assert env.oa_results.saved == []


def test_run_case_입력을_못_만들면_failed(env):
    st = env.run(run_id="r_9", oa_id="없음")
    assert st.state == RunState.FAILED and st.error["code"] == "step_failed"
    assert "RunInputNotFound" in st.error["message"]


def test_run_case_지휘가_예상_밖_예외를_내도_failed로_남는다(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("검색 DB 연결 문자열 postgres://비밀")

    monkeypatch.setattr("patent_ai.core.runs.run_case_executor.run_case", boom)
    st = env.run()
    assert st.state == RunState.FAILED and st.error["code"] == "step_failed"
    assert "비밀" not in st.error["message"]
    assert env.registry.is_requested(RID) is False


def test_run_case_사람을_기다리면_waiting_for_human이고_그때까지_정리는_저장된다(
    tmp_path, monkeypatch
):
    oa = wire(monkeypatch)
    unknown = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
    oa = oa.model_copy(
        update={"application_number": oa.application_number.model_copy(update={"status": unknown})}
    )
    monkeypatch.setattr("patent_ai.core.f1_oa_reader.read_oa.read_oa", lambda *a, **k: oa)
    env = Env(tmp_path)
    st = env.run()
    assert st.state == RunState.WAITING_FOR_HUMAN and st.waiting_for == "application_number"
    assert [run for _, run, _ in env.oa_results.saved] == [RID]
    assert env.step_results.step_result(RID, "f3") is None  # F3 전에 멈춤


def test_run_case_도는_중에_취소하면_다음_단계_전에_cancelled이고_결과를_안_남긴다(env):
    # F1이 끝나 "자르는 중"으로 바뀌는 순간 취소 API가 불린 것처럼 한다
    real = env.store.set_current_step

    def set_and_cancel(run_id, step):
        real(run_id, step)
        if step == "OA 시점까지 자료 자르는 중":
            request_cancel(run_id, env.store, env.registry)

    env.store.set_current_step = set_and_cancel
    st = env.run()
    assert st.state == RunState.CANCELLED
    assert env.oa_results.saved == [] and env.step_results.step_result(RID, "f3") is None
    assert env.registry.is_requested(RID) is False  # 끝나면 표시를 지운다


def test_run_case_기다리는_동안_취소된_실행은_돌지_않는다(env):
    env.store.add(RID, OID)
    request_cancel(RID, env.store, env.registry)  # queued -> cancelled
    st = env.run()
    assert st.state == RunState.CANCELLED
    assert env.inputs.called == []


def test_run_case_서버에서는_한_번에_하나만_돈다(env):
    gate = threading.Event()
    env.inputs.gate = gate
    env.store.add("r_a", OID)
    env.store.add("r_b", "oa_2")
    first = threading.Thread(target=env.executor.execute, args=("r_a", OID))
    second = threading.Thread(target=env.executor.execute, args=("r_b", "oa_2"))
    first.start()
    # 첫 실행이 입력 만들기에서 멈춰 있는 동안
    for _ in range(500):
        if env.inputs.called:
            break
        threading.Event().wait(0.01)
    second.start()
    second.join(0.2)
    assert env.store.get_status("r_a").state == RunState.RUNNING
    assert env.store.get_status("r_b").state == RunState.QUEUED  # 잠금을 기다린다
    gate.set()
    first.join(10)
    second.join(10)
    assert env.store.get_status("r_a").state == RunState.SUCCEEDED
    assert env.store.get_status("r_b").state == RunState.SUCCEEDED
