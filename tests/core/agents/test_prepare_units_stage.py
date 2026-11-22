"""prepare_units 고정 단계 (이슈 #309 task-2): cut_to_oa -> prepare_units -> decide 고정 간선.

가짜 전송층·메모리 검색 자원. 지휘가 건너뛸 수 없고, max_steps에 안 센다.
"""

import pytest

from patent_ai.core.agents.step_inputs import InputMissing, f2_input, f3_input, prepare_input
from patent_ai.core.agents.tools import ToolRegistry
from patent_ai.core.agents.tools_f3 import register_f3_tools
from patent_ai.core.f3_claim_compare.config import load_f3_settings
from patent_ai.core.f3_claim_compare.inputs import F3Config
from patent_ai.core.f3_claim_compare.run import PreparedUnits, run_f3
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport, TransportResponse
from patent_ai.core.schemas.case_materials import CaseMaterials
from patent_ai.core.schemas.document import PageText
from patent_ai.core.schemas.oa_result import OAResult
from tests.core.agents import test_fixed_order_f3_f4 as base
from tests.core.f3 import scenario
from tests.core.f3.fakes import claim_row

TRACE = ["extract_pages", "read_oa", "cut_to_oa", "prepare_units", "run_f3", "run_f2", "run_f4"]


@pytest.fixture
def wired(monkeypatch):
    pages = PageText.model_validate_json((base.F1 / "notice_basic.pages.json").read_text("utf-8"))
    oa = OAResult.model_validate(
        {**base.CASE["oa"], "claim_rows": [claim_row(2, 2, clarity_terms=[base.TERM]).model_dump()]}
    )
    monkeypatch.setattr("patent_ai.core.f1_oa_reader.pages.extract_pages", lambda p, d: pages)
    monkeypatch.setattr("patent_ai.core.f1_oa_reader.read_oa.read_oa", lambda *a, **k: oa)
    monkeypatch.setattr(
        base.f3_run,
        "make_search_resources",
        lambda config, ctx: (scenario.searcher(), scenario.REPO),
    )
    monkeypatch.setattr(base.f2_run, "make_law_repo", base.f2_fakes.repo)
    return oa


def test_고정_순서_단계_기록이_prepare_units를_cut_to_oa_뒤_run_f3_앞에_둔다(tmp_path, wired):
    out, steps = base._go(tmp_path)
    assert out.state == "succeeded"
    assert out.trace == TRACE
    assert [r.tool_name for r in steps.records] == TRACE
    assert isinstance(out.results["prepare_units"], PreparedUnits)
    assert out.skipped == {}


def test_agent_모드에서도_지휘가_고르지_않아도_같은_간선을_지난다(tmp_path, wired):
    responses = base._responses()
    responses["agents.orchestrator"] = [
        base._text({"next_tool": n, "reason": "차례"}) for n in ("read_oa", "run_f3", "stop")
    ]
    out, _ = base._go(tmp_path, responses, plan="agent")
    assert out.trace == ["extract_pages", "read_oa", "cut_to_oa", "prepare_units", "run_f3"]


def test_run_f3_결과는_prepared_없이_돈_결과와_같고_나누기는_한_번씩만_부른다(tmp_path, wired):
    out, steps = base._go(tmp_path)
    calls = {r.tool_name: r.model_call_count for r in steps.records}
    assert calls["prepare_units"] == 2  # 청구항 둘 나누기는 여기서만
    assert calls["prepare_units"] + calls["run_f3"] == 5  # 지금까지 run_f3 한 단계의 호출 수

    # prepared 없이 직접 돌린 F3Result와 같다
    transport = FakeTransport(base._responses())
    ctx = RunContext(
        run_id="r_2", budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
    )
    direct = run_f3(
        wired,
        CaseMaterials(case_id="c_1"),
        F3Config(settings=load_f3_settings(), inputs=base._texts()),
        ctx=ctx,
        searcher=scenario.searcher(),
        repo=scenario.REPO,
    )
    assert out.results["run_f3"] == direct


def test_F2_입력_units는_prepare_units_결과의_units와_같다(tmp_path, wired):
    out, _ = base._go(tmp_path)
    f2 = f2_input(out.results, base.CHECKED_ON)
    assert f2["units"] == out.results["prepare_units"].units
    # 없을 때만 run_f3의 units (F2 인터페이스 그대로)
    without = {k: v for k, v in out.results.items() if k != "prepare_units"}
    assert f2_input(without, base.CHECKED_ON)["units"] == out.results["run_f3"].units


def test_f3_입력은_prepare_units_결과가_있으면_prepared로_넘긴다(tmp_path, wired):
    out, _ = base._go(tmp_path)
    payload = f3_input(out.results, "c_1", base._texts())
    assert payload["prepared"] == out.results["prepare_units"]
    assert f3_input({"read_oa": wired}, "c_1", base._texts()).get("prepared") is None


def test_prepare_input은_글자나_OA가_없으면_InputMissing이다(wired):
    assert isinstance(prepare_input({}, "c_1", base._texts()), InputMissing)
    assert isinstance(prepare_input({"read_oa": wired}, "c_1", None), InputMissing)
    ok = prepare_input({"read_oa": wired}, "c_1", base._texts())
    assert set(ok) == {"oa_result", "config"}


def test_청구항_글자가_없으면_prepare_units_run_f3_run_f2가_같은_이유로_skipped(tmp_path, wired):
    out, steps = base._go(tmp_path, responses={}, texts=None)
    assert list(out.skipped) == ["prepare_units", "run_f3", "run_f2", "run_f4"]
    assert out.skipped["prepare_units"] == out.skipped["run_f3"]
    assert out.skipped["prepare_units"].startswith("input_unverified")
    assert out.trace == ["extract_pages", "read_oa", "cut_to_oa"]
    rec = next(r for r in steps.records if r.tool_name == "prepare_units")
    assert rec.outcome == "skipped" and rec.skipped_reason == out.skipped["prepare_units"]


def test_prepare_units_모델_호출이_실패하면_실행이_failed이고_코드가_같다(tmp_path, wired):
    responses = base._responses()
    broken = TransportResponse("JSON 아님", 10, 10)
    responses["f3.split_elements"] = [broken, broken]
    out, steps = base._go(tmp_path, responses)
    assert out.state == "failed" and out.error["code"] == "ModelOutputInvalid"
    assert out.trace == ["extract_pages", "read_oa", "cut_to_oa"]
    assert (steps.records[-1].tool_name, steps.records[-1].outcome) == ("prepare_units", "failed")


def test_prepare_units는_fixed_stage라_지휘_도구_목록에_없다():
    reg = ToolRegistry()
    register_f3_tools(reg)
    assert reg.get("prepare_units").kind == "fixed_stage"
    assert "prepare_units" not in {t.name for t in reg.list(kind="code_tool")}


def test_prepare_units는_사건_채우기가_만든_글자를_읽는다(tmp_path, monkeypatch):
    # #314 fill_case 뒤로 이음: 실행 입력 글자가 없어도 사건 채우기 글자(state texts)로 나눈다
    from patent_ai.core.agents import orchestrator
    from patent_ai.core.agents.orchestrator import FilledTexts
    from tests.core.agents.test_fill_case import TEXTS, Filler, _go

    seen: list = []

    def spy(results, case_id, texts):
        seen.append(texts)
        return InputMissing("input_unverified: 테스트에서 나누기는 안 돌림")

    monkeypatch.setattr(orchestrator, "prepare_input", spy)
    monkeypatch.setattr(
        orchestrator, "f3_input", lambda *a: InputMissing("input_unverified: F3 안 돌림")
    )
    _, records = _go(tmp_path, Filler(FilledTexts(texts=TEXTS, reason="채움")), texts=None)
    assert seen == [TEXTS]
    names = [r.tool_name for r in records]
    assert names.index("fill_case") < names.index("cut_to_oa") < names.index("prepare_units")
