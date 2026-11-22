"""단계 기록에 저장한 단계 결과 ID 붙이기 (이슈 #267).

확인: uv run pytest tests/core/runs -k result_link

결과를 저장한 단계(run_f2·run_f3·run_f4)의 StepRecord.result_id가 step_results ID를 가리키고,
결과를 안 만든 단계(skipped·failed)는 None 그대로다. 네트워크·키·DB 없음.
"""

import pytest

from patent_ai.core.agents.steps import MemoryStepRecorder, StepRecord
from tests.core.run_case_fakes import wire
from tests.core.runs.test_run_case_executor import OID, RID, Env

RESULT_STEPS = {"run_f2": "f2", "run_f3": "f3", "run_f4": "f4"}


def _step(tool, outcome):
    return StepRecord(
        run_id=RID, step_kind="code_tool", tool_name=tool, reason="이유", outcome=outcome
    )


def test_memory_link_result는_그_도구의_ok_줄에만_ID를_붙인다():
    rec = MemoryStepRecorder()
    rec.record(_step("run_f3", "failed"))
    rec.record(_step("run_f3", "ok"))
    rec.record(_step("run_f2", "skipped"))
    rec.link_result(RID, "run_f3", "sres_1")
    assert [(r.tool_name, r.outcome, r.result_id) for r in rec.records] == [
        ("run_f3", "failed", None),
        ("run_f3", "ok", "sres_1"),
        ("run_f2", "skipped", None),
    ]


def test_memory_link_result_붙일_줄이_없으면_경고하고_아무것도_안_바꾼다(caplog):
    rec = MemoryStepRecorder()
    rec.record(_step("run_f2", "skipped"))
    with caplog.at_level("WARNING"):
        rec.link_result(RID, "run_f2", "sres_1")
    assert rec.records[0].result_id is None
    assert "run_f2" in caplog.text


def _capture_ids(env):
    """저장소가 돌려준 ID를 단계별로 모은다 (실행기가 같은 ID를 기록에 붙이는지 비교하려고)."""
    ids: dict[str, str] = {}
    real = env.step_results.save_step_result

    def save(oa_id, run_id, body):
        new = real(oa_id, run_id, body)
        ids[type(body).__name__] = new
        return new

    env.step_results.save_step_result = save
    return ids


@pytest.fixture
def linked(tmp_path, monkeypatch):
    wire(monkeypatch)
    rec = MemoryStepRecorder()
    return Env(tmp_path, step_log=rec), rec


def test_실행_한_바퀴_뒤_결과를_저장한_단계는_그_결과_ID를_가리킨다(linked):
    env, rec = linked
    ids = _capture_ids(env)
    assert env.run().state.value == "succeeded"
    by_tool = {r.tool_name: r for r in rec.records if r.outcome == "ok"}
    assert set(RESULT_STEPS) <= set(by_tool)
    saved = {
        "run_f2": ids["F2Result"],
        "run_f3": ids["F3Result"],
        "run_f4": ids["F4Output"],
    }
    for tool, sid in saved.items():
        assert by_tool[tool].result_id == sid
        assert sid  # 빈 ID가 아니다
    # 결과를 step_results에 저장하지 않는 단계는 None (read_oa는 이 이슈 범위 밖)
    others = [r for r in rec.records if r.tool_name not in RESULT_STEPS]
    assert others and all(r.result_id is None for r in others)


def test_글자가_없어_F3_F2_F4를_넘기면_그_단계_result_id는_None(tmp_path, monkeypatch):
    wire(monkeypatch)
    rec = MemoryStepRecorder()
    env = Env(tmp_path, with_texts=False, step_log=rec)
    env.run(RID, OID)
    skipped = [r for r in rec.records if r.outcome == "skipped"]
    assert {r.tool_name for r in skipped} == set(RESULT_STEPS)
    assert all(r.result_id is None for r in rec.records)
