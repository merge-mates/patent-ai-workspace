"""run_case 실행기 (이슈 #191 T1). 확인: uv run pytest tests/core/runs -k run_case

#180 한 바퀴(F1 → F3 → F2 넘김 → F4)를 가짜 응답으로 돌리고, 실행 상태·결과 저장을 본다.
네트워크·키·DB 없음.
"""

import logging
import threading
from datetime import timedelta

import pytest

from patent_ai.core.agents.orchestrator import CaseInput, FilledTexts
from patent_ai.core.cases.human_inputs import InMemoryHumanInputStore
from patent_ai.core.cases.results import InMemoryOAResultStore
from patent_ai.core.cases.run_inputs import RunInputNotFound
from patent_ai.core.cases.selections import InMemorySelectionStore
from patent_ai.core.cases.step_results import InMemoryStepResultStore
from patent_ai.core.runs.cancel import CancelRegistry, request_cancel
from patent_ai.core.runs.run_case_executor import RunCaseExecutor
from patent_ai.core.runs.state import RunState
from patent_ai.core.schemas.common import Origin, Status, StatusValue, UnverifiedReason
from patent_ai.core.schemas.direction import DirectionSelection
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


class _CaseFill:
    """F1 뒤 사건 채우기 기록 (#261). 채우는 규칙은 tests/core/cases/test_case_fill.py가 본다."""

    def __init__(self):
        self.calls: list[tuple] = []

    def fill_after_f1(self, oa_id, run_id, result, text_status):
        self.calls.append((oa_id, run_id, result.oa_id, text_status))


class Env:
    def __init__(
        self, tmp_path, *, with_texts=True, cases=None, store=None, step_log=None, fill_case=None
    ):
        self.store = store or MemoryStatusStore()
        self.registry = CancelRegistry()
        self.oa_results = InMemoryOAResultStore(self.store)
        self.step_results = InMemoryStepResultStore()
        self.case_fill = _CaseFill()
        self.inputs = _Inputs(tmp_path, with_texts)
        self.selections = InMemorySelectionStore()
        self.human = InMemoryHumanInputStore()
        self.lock = threading.Lock()
        self.executor = RunCaseExecutor(
            store=self.store,
            registry=self.registry,
            oa_results=self.oa_results,
            step_results=self.step_results,
            case_fill=self.case_fill,
            inputs=self.inputs,
            cases=cases or _Cases(),
            config_path=real_config(tmp_path),
            make_ctx=fake_ctx,
            today=lambda: CHECKED_ON,
            selections=self.selections,
            human=self.human,
            lock=self.lock,
            step_log=step_log,
            fill_case=fill_case,
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


def test_run_case_한_바퀴가_끝나면_succeeded이고_F1_F2_F3_F4_결과가_저장된다(env):
    st = env.run()
    assert st.state == RunState.SUCCEEDED and st.error is None
    assert [(oa, run) for oa, run, _ in env.oa_results.saved] == [(OID, RID)]
    f3, f4 = env.step_results.step_result(RID, "f3"), env.step_results.step_result(RID, "f4")
    assert f3 is not None and f3.units and f3.comparisons
    assert f4 is not None and f4.directions
    # F2도 돌아 넘긴 단계가 없고, F2 결과(판단 단위마다 법률 근거 묶음)도 저장된다
    assert env.store.skipped_steps(RID) == []
    f2 = env.step_results.step_result(RID, "f2")
    assert f2 is not None and [b.unit_id for b in f2.bundles] == [u.unit_id for u in f3.units]


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


class _FillCase:
    """F1 뒤·F3 앞 사건 채우기 (#54). 채우는 규칙은 tests/core/cases/case_source가 본다."""

    def __init__(self):
        self.calls: list[tuple] = []

    def fill(self, oa_id, application_number, dispatch_number):
        self.calls.append((oa_id, application_number, dispatch_number))
        return FilledTexts(texts=texts(), reason="local_folder로 채움")


def test_run_case_실행_입력에_글자가_없어도_사건을_채우면_F3_F4까지_돈다(tmp_path, monkeypatch):
    wire(monkeypatch)
    fill = _FillCase()
    env = Env(tmp_path, with_texts=False, fill_case=fill)
    st = env.run()
    assert st.state == RunState.SUCCEEDED
    assert [c[0] for c in fill.calls] == [OID]
    assert env.step_results.step_result(RID, "f3") is not None
    assert env.step_results.step_result(RID, "f4") is not None
    assert env.store.skipped_steps(RID) == []


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
    # 사람 기다림에서도 사건 채우기를 부른다 (못 읽은 출원번호는 채우기 쪽이 넣지 않음, #261)
    assert [(c[0], c[1]) for c in env.case_fill.calls] == [(OID, RID)]


def test_run_case_발송번호를_기다릴_때도_사건_채우기를_부른다(tmp_path, monkeypatch):
    # 출원번호는 읽었으니 사건 이름·사건 자료는 채운다 (발송번호는 채우기 쪽이 넣지 않음, #261)
    oa = wire(monkeypatch)
    unknown = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
    oa = oa.model_copy(
        update={"dispatch_number": oa.dispatch_number.model_copy(update={"status": unknown})}
    )
    monkeypatch.setattr("patent_ai.core.f1_oa_reader.read_oa.read_oa", lambda *a, **k: oa)
    env = Env(tmp_path)
    st = env.run()
    assert st.state == RunState.WAITING_FOR_HUMAN and st.waiting_for == "dispatch_number"
    assert [(c[0], c[1]) for c in env.case_fill.calls] == [(OID, RID)]


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


def test_run_case_F1_정리를_저장한_뒤_사건_번호와_사건_자료를_채운다(env):
    # #261: 채우기가 없으면 사건 이름이 "출원번호 확인 전"에 남고 사건 자료가 404다
    st = env.run()
    assert st.state == RunState.SUCCEEDED
    assert [(oa, run, res_oa) for oa, run, res_oa, _ in env.case_fill.calls] == [(OID, RID, OID)]
    assert env.case_fill.calls[0][3] is not None  # 글자 추출 상태를 넘긴다


def test_run_case_실패하면_사건을_채우지_않는다(tmp_path, monkeypatch):
    wire(monkeypatch)
    env = Env(tmp_path, cases=_Cases(found=("c_옛", "oa_옛")))
    env.run()
    assert env.case_fill.calls == []


def test_run_case_사건_채우기가_실패하면_failed_result_save_failed(env):
    def boom(*a):
        raise RuntimeError("postgres://비밀")

    env.case_fill.fill_after_f1 = boom
    st = env.run()
    assert st.state == RunState.FAILED and st.error["code"] == "result_save_failed"
    assert "비밀" not in st.error["message"]


# ---- 초안만 다시 만드는 작은 실행 (kind = redo_drafts, #70) ----
# 실패를 succeeded로 돌려주지 않는다: 실패·취소면 이유를 남기고 이 실행에 결과를 저장하지 않는다.
REDO = "r_redo"
UNIT = "oa_1:29-2:c1"


def _redo(env, *, pick=True):
    """끝까지 돈 실행 하나 뒤에, 그 OA의 작은 실행 하나를 돌린다."""
    assert env.run().state == RunState.SUCCEEDED
    env.store.add(REDO, OID, kind="redo_drafts")
    if pick:
        sel = DirectionSelection(candidate_id=f"{UNIT}:d1", origin=Origin.HUMAN_SELECTED)
        env.selections.save_selection(OID, UNIT, sel, run_id=REDO)
    env.executor.execute(REDO, OID)
    return env.store.get_status(REDO)


def _nothing_saved(env):
    return all(run != REDO for _, run, _ in env.oa_results.saved) and all(
        env.step_results.step_result(REDO, k) is None for k in ("f2", "f3", "f4")
    )


def test_redo_고른_묶음만_바꿔_초안을_다시_만들고_앞_결과를_옮긴다(env):
    st = _redo(env)
    assert st.state == RunState.SUCCEEDED, st.error
    f4 = env.step_results.step_result(REDO, "f4")
    by_unit = {d.unit_id: d for d in f4.directions}
    assert by_unit[UNIT].selection.origin == Origin.HUMAN_SELECTED
    assert env.step_results.step_result(REDO, "f3") == env.step_results.step_result(RID, "f3")
    assert [run for _, run, _ in env.oa_results.saved] == [RID, REDO]


def test_redo_앞_F4가_없으면_failed_no_previous_drafts(tmp_path, monkeypatch):
    wire(monkeypatch)
    env = Env(tmp_path, with_texts=False)  # 글자가 없어 F3·F4를 넘긴 앞 실행
    st = _redo(env)
    assert st.state == RunState.FAILED and st.error["code"] == "no_previous_drafts"
    assert _nothing_saved(env)


def test_redo_이_실행에_묶인_선택이_없으면_failed_no_selection(env):
    st = _redo(env, pick=False)
    assert st.state == RunState.FAILED and st.error["code"] == "no_selection"
    assert _nothing_saved(env)


def test_redo_입력을_못_만들면_failed(env):
    assert env.run().state == RunState.SUCCEEDED
    env.inputs.with_texts = False  # 이번에는 글자가 없다
    env.store.add(REDO, OID, kind="redo_drafts")
    env.selections.save_selection(
        OID,
        UNIT,
        DirectionSelection(candidate_id=f"{UNIT}:d1", origin=Origin.HUMAN_SELECTED),
        run_id=REDO,
    )
    env.executor.execute(REDO, OID)
    st = env.store.get_status(REDO)
    assert st.state == RunState.FAILED and st.error["code"] == "step_failed"
    assert "input_unverified" in st.error["message"]
    assert _nothing_saved(env)


def test_redo_초안_만들기가_예외면_failed이고_원문은_이유에_없다(env, monkeypatch):
    import patent_ai.core.runs.run_case_executor as mod

    def boom(*a, **k):
        raise RuntimeError("비밀 원문 글자")

    monkeypatch.setattr(mod, "redo_drafts", boom)
    st = _redo(env)
    assert st.state == RunState.FAILED and st.error["code"] == "step_failed"
    assert "비밀 원문 글자" not in st.error["message"]
    assert _nothing_saved(env)


def test_redo_끝난_뒤_취소_표시가_있으면_cancelled이고_결과를_안_남긴다(env, monkeypatch):
    import patent_ai.core.runs.run_case_executor as mod

    real = mod.redo_drafts

    def cancel_after(*a, **k):
        out = real(*a, **k)
        request_cancel(REDO, env.store, env.registry)  # running이라 표시만
        return out

    monkeypatch.setattr(mod, "redo_drafts", cancel_after)
    st = _redo(env)
    assert st.state == RunState.CANCELLED
    assert _nothing_saved(env)


def test_redo_결과_저장이_실패하면_failed_result_save_failed(env, monkeypatch):
    assert env.run().state == RunState.SUCCEEDED
    real = env.step_results.save_step_result

    def fail_for_redo(oa_id, run_id, body):
        if run_id == REDO:
            raise RuntimeError("저장 실패")
        real(oa_id, run_id, body)

    monkeypatch.setattr(env.step_results, "save_step_result", fail_for_redo)
    env.store.add(REDO, OID, kind="redo_drafts")
    env.selections.save_selection(
        OID,
        UNIT,
        DirectionSelection(candidate_id=f"{UNIT}:d1", origin=Origin.HUMAN_SELECTED),
        run_id=REDO,
    )
    env.executor.execute(REDO, OID)
    st = env.store.get_status(REDO)
    assert st.state == RunState.FAILED and st.error["code"] == "result_save_failed"


# ---- 사람 기다림에서 이어 돌기 (#70 계획 ②) ----
def _waiting(tmp_path, monkeypatch):
    oa = wire(monkeypatch)
    unknown = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)
    oa = oa.model_copy(
        update={"application_number": oa.application_number.model_copy(update={"status": unknown})}
    )
    monkeypatch.setattr("patent_ai.core.f1_oa_reader.read_oa.read_oa", lambda *a, **k: oa)
    env = Env(tmp_path)
    assert env.run().state == RunState.WAITING_FOR_HUMAN
    return env


def test_resume_아직_기다리는_실행은_돌리지_않는다(tmp_path, monkeypatch):
    # 사람 입력 API가 queued로 바꾼 뒤에만 이어 돈다: 기다리는 실행을 몰래 처음부터 돌리지 않는다
    env = _waiting(tmp_path, monkeypatch)
    saved_before = list(env.oa_results.saved)
    env.executor.execute(RID, OID)
    st = env.store.get_status(RID)
    assert st.state == RunState.WAITING_FOR_HUMAN
    assert env.oa_results.saved == saved_before


def test_resume_저장한_정리가_없으면_failed_no_saved_oa_result(tmp_path, monkeypatch):
    wire(monkeypatch)
    env = Env(tmp_path)
    env.store.add(RID, OID)  # 번호를 넣어 queued가 된 실행처럼
    env.human.add(OID, RID, "application_number", "1020990000001")
    env.executor.execute(RID, OID)
    st = env.store.get_status(RID)
    assert st.state == RunState.FAILED and st.error["code"] == "no_saved_oa_result"


def test_resume_번호를_넣으면_같은_실행이_끝까지_돌고_결과가_저장된다(tmp_path, monkeypatch):
    env = _waiting(tmp_path, monkeypatch)
    env.store.transition(RID, RunState.QUEUED, expected=RunState.WAITING_FOR_HUMAN)
    env.human.add(OID, RID, "application_number", "1020990000001")
    env.executor.execute(RID, OID)
    st = env.store.get_status(RID)
    assert st.state == RunState.SUCCEEDED and st.waiting_for is None
    assert env.step_results.step_result(RID, "f4") is not None


# ---- 작은 실행의 확인 기준일 (#293): 날을 넘겨 골라도 앞 실행(방향 후보)의 기준일을 쓴다 ----
LATER = CHECKED_ON + timedelta(days=3)


def _redo_on_later_day(env, prev_f4_update=None, drop_f2=False):
    """앞 실행은 CHECKED_ON에 돌고, 사람은 사흘 뒤에 고른다. 앞 결과를 바꿔 끼울 수 있다."""
    assert env.run().state == RunState.SUCCEEDED
    real = env.step_results.step_result

    def prev(run_id, kind):
        body = real(run_id, kind)
        if run_id == RID and kind == "f4" and prev_f4_update is not None:
            return body.model_copy(update=prev_f4_update)
        if run_id == RID and kind == "f2" and drop_f2:
            return None
        return body

    env.step_results.step_result = prev
    env.executor._today = lambda: LATER
    env.store.add(REDO, OID, kind="redo_drafts")
    sel = DirectionSelection(candidate_id=f"{UNIT}:d1", origin=Origin.HUMAN_SELECTED)
    env.selections.save_selection(OID, UNIT, sel, run_id=REDO)
    env.executor.execute(REDO, OID)
    assert env.store.get_status(REDO).state == RunState.SUCCEEDED, env.store.get_status(REDO)
    return real(REDO, "f4")


def test_redo_날을_넘겨_골라도_앞_실행의_확인_기준일을_쓴다(env):
    assert _redo_on_later_day(env).checked_on == CHECKED_ON


def test_redo_옛_F4에_기준일이_없으면_앞_F2_묶음의_기준일을_쓴다(env, caplog):
    with caplog.at_level(logging.WARNING):
        out = _redo_on_later_day(env, {"checked_on": None})
    assert out.checked_on == CHECKED_ON
    # 앞 F2 기준일로 이어 쓸 수 있으면 오늘로 대신하지 않으니 경고도 없다
    assert "확인 기준일" not in caplog.text


def test_redo_앞_기준일을_모르면_오늘을_쓰고_경고한다(env, caplog):
    with caplog.at_level(logging.WARNING):
        out = _redo_on_later_day(env, {"checked_on": None}, drop_f2=True)
    assert out.checked_on == LATER
    assert "확인 기준일" in caplog.text
