"""사람 방향 고르기 API (이슈 #70 ①-4). 확인: uv run pytest tests/api -k directions_api

진짜 실행기 + 메모리 저장소 + 기록된 응답. 명확성 묶음은 확신 낮은 후보(순위 없음)로 만들어
사람이 고르기 전에는 그 묶음 초안이 없고, 고르면 작은 실행이 초안을 다시 만드는지 본다.
"""

import pytest

import patent_ai.core.cases.store as store_mod
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.transport import FakeTransport
from patent_ai.core.runs.state import RunState
from tests.api.test_results_api import _Inputs
from tests.core.agents.test_fixed_order_f3_f4 import _f4
from tests.core.run_case_app import RunCaseApp
from tests.core.run_case_fakes import responses, wire

INVENTIVE = "oa_1:29-2:c1"
CLARITY = "oa_1:42-4-2:c2"
LOW_PICK = f"{CLARITY}:d2"  # amend_only: 명확성 의견서·보정 녹화 답과 모양이 맞는 후보


class _Ctx:
    """실행마다 새 맥락. 명확성 방향 답을 확신 낮음으로 바꾸고, 부른 단계를 실행별로 모은다."""

    def __init__(self):
        self.calls: dict[str, list[str]] = {}

    def __call__(self, run_id: str) -> RunContext:
        answers = responses()
        answers["f4.direction"] = _f4("direction_inventive", "direction_low")
        transport = FakeTransport(answers)
        self.calls[run_id] = transport.calls  # 같은 목록을 들고 있어 나중에 본다
        return RunContext(
            run_id=run_id, budget=CallBudget(), recorder=MemoryRecorder(), transport=transport
        )


@pytest.fixture
def env(tmp_path, monkeypatch):
    wire(monkeypatch)
    # 지어낸 OA 정리의 묶음 ID가 oa_1로 시작한다: 올린 OA ID도 oa_1로 맞춘다 (진짜 앱은 read_oa가
    # 올린 OA ID로 정리를 만들어 묶음 ID 맨 앞이 늘 그 OA다)
    real_new_id = store_mod.new_id
    monkeypatch.setattr(store_mod, "new_id", lambda k: "oa_1" if k == "oa" else real_new_id(k))
    ctx = _Ctx()
    app = RunCaseApp(tmp_path, make_inputs=lambda cases: _Inputs(tmp_path, True), make_ctx=ctx)
    app.ctx = ctx
    return app


def _put(env, unit_id, body):
    return env.client.put(f"/directions/{unit_id}/selection", json=body)


def _units(env, oa_id):
    return {d["unit_id"]: d for d in env.get(oa_id, "directions").json()["result"]}


def test_directions_api_확신_낮은_묶음은_고르기_전에도_후보가_보이고_초안은_없다(env):
    created = env.upload()
    oa_id = created["oa_id"]
    # 방향 고르기로 실행을 멈추지 않는다 (#70: 실행은 끝나고 그 묶음만 보류)
    assert env.client.get(f"/runs/{created['run_id']}").json()["state"] == "succeeded"

    low = _units(env, oa_id)[CLARITY]
    assert low["selection"] is None
    assert [c["candidate_id"] for c in low["candidates"]] == [f"{CLARITY}:d1", LOW_PICK]
    drafts = env.get(oa_id, "drafts").json()
    assert drafts["held_units"] == [CLARITY]
    assert CLARITY not in [b["unit_id"] for b in drafts["result"]["based_on"]]


def test_directions_api_고르면_작은_실행이_그_묶음_초안을_만들고_방향_후보는_다시_안_부른다(env):
    oa_id = env.upload()["oa_id"]

    res = _put(env, CLARITY, {"candidate_id": LOW_PICK})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["unit_id"] == CLARITY
    assert body["selection"] == {
        "candidate_id": LOW_PICK,
        "written_direction": None,
        "origin": "human_selected",
    }
    run_id = body["run_id"]
    assert env.client.get(f"/runs/{run_id}").json()["state"] == "succeeded"
    assert "f4.direction" not in [c["step"] for c in env.ctx.calls[run_id]]
    # 결과는 모두 새 작은 실행에서 열린다 (OA 정리·F3·F2를 옮김)
    for name in ("units", "legal-evidence", "directions", "drafts"):
        assert env.get(oa_id, name).json()["run_id"] == run_id, name
    assert env.client.get(f"/oas/{oa_id}/oa-result").json()["run_id"] == run_id
    drafts = env.get(oa_id, "drafts").json()
    assert drafts["held_units"] == []
    assert (CLARITY, LOW_PICK) in [
        (b["unit_id"], b["candidate_id"]) for b in drafts["result"]["based_on"]
    ]
    units = _units(env, oa_id)
    assert units[CLARITY]["selection"]["origin"] == "human_selected"
    assert units[INVENTIVE]["selection"]["origin"] == "ai_default"  # 다른 묶음은 그대로


def test_directions_api_직접_쓴_방향은_기록되고_그_묶음_초안은_보류로_남는다(env):
    oa_id = env.upload()["oa_id"]

    res = _put(env, CLARITY, {"written_direction": "청구항 2 문구를 고쳐 명확히"})

    assert res.status_code == 200, res.text
    run_id = res.json()["run_id"]
    assert env.client.get(f"/runs/{run_id}").json()["state"] == "succeeded"
    sel = _units(env, oa_id)[CLARITY]["selection"]
    assert sel == {
        "candidate_id": None,
        "written_direction": "청구항 2 문구를 고쳐 명확히",
        "origin": "human_written",
    }
    assert env.get(oa_id, "drafts").json()["held_units"] == [CLARITY]
    assert env.selections.selections_for_run(run_id)[CLARITY].origin == "human_written"


def test_directions_api_나중에_고른_것이_이긴다(env):
    oa_id = env.upload()["oa_id"]
    _put(env, CLARITY, {"written_direction": "먼저 쓴 방향"})
    _put(env, CLARITY, {"candidate_id": LOW_PICK})

    assert _units(env, oa_id)[CLARITY]["selection"]["candidate_id"] == LOW_PICK
    assert env.get(oa_id, "drafts").json()["held_units"] == []


@pytest.mark.parametrize(
    "unit_id, body, status, code",
    [
        ("oa_없음:29-2:c1", {"candidate_id": "x"}, 404, "oa_not_found"),
        ("oa_1:29-2:c9", {"candidate_id": "x"}, 404, "unit_not_found"),
        (CLARITY, {"candidate_id": f"{CLARITY}:d9"}, 422, "candidate_not_found"),
        (CLARITY, {}, 422, "invalid_selection"),
        (
            CLARITY,
            {"candidate_id": LOW_PICK, "written_direction": "둘 다"},
            422,
            "invalid_selection",
        ),
        (CLARITY, {"written_direction": "   "}, 422, "invalid_selection"),
    ],
)
def test_directions_api_잘못된_선택은_오류이고_기록도_실행도_안_남는다(
    env, unit_id, body, status, code
):
    created = env.upload()
    res = _put(env, unit_id, body)
    assert (res.status_code, res.json()["code"]) == (status, code)
    assert env.selections._rows == []  # 기록이 안 남는다
    assert env.cases.get_oa(created["oa_id"]).latest_run.id == created["run_id"]


def test_directions_api_결과_전이면_result_not_ready(env):
    env.launch_enabled = False  # 실행이 queued로 남는다
    created = env.upload()
    env.runs.transition(created["run_id"], RunState.CANCELLED)
    res = _put(env, CLARITY, {"candidate_id": LOW_PICK})
    assert (res.status_code, res.json()["code"]) == (404, "result_not_ready")


def test_directions_api_진행_중_실행이_있으면_409(env):
    created = env.upload()
    env.launch_enabled = False
    env.client.post(f"/oas/{created['oa_id']}/runs")  # queued로 남는 새 실행
    res = _put(env, CLARITY, {"candidate_id": LOW_PICK})
    assert (res.status_code, res.json()["code"]) == (409, "run_in_progress")


def test_directions_api_다시_돌린_뒤_다른_묶음을_골라도_옛_선택이_되살아나지_않는다(env):
    # 리뷰 막음 재현: A 고름 → 끝까지 다시 돌리기 → B 고름 → A는 새 후보 위에서 사람이 안 고름
    oa_id = env.upload()["oa_id"]
    _put(env, CLARITY, {"candidate_id": LOW_PICK})
    rerun = env.client.post(f"/oas/{oa_id}/runs").json()["run_id"]
    assert env.client.get(f"/runs/{rerun}").json()["state"] == "succeeded"
    assert _units(env, oa_id)[CLARITY]["selection"] is None  # 새 후보, 아직 안 고름

    res = _put(env, INVENTIVE, {"candidate_id": f"{INVENTIVE}:d1"})

    assert env.client.get(f"/runs/{res.json()['run_id']}").json()["state"] == "succeeded"
    units = _units(env, oa_id)
    assert units[CLARITY]["selection"] is None
    assert units[INVENTIVE]["selection"]["origin"] == "human_selected"
    assert env.get(oa_id, "drafts").json()["held_units"] == [CLARITY]
