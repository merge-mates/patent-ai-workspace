"""사람이 번호를 넣으면 기다리던 실행이 이어 돌기, 정리 결과 "맞아요" (이슈 #70 계획 ②).

확인: uv run pytest tests/api -k human_inputs_api
진짜 실행기 + 메모리 저장소 + 기록된 응답. 네트워크·키·DB 없음.
"""

import pytest

import patent_ai.core.f1_oa_reader.read_oa as read_oa_mod
from patent_ai.core.cases.human_answers import HUMAN_CHECKED
from patent_ai.core.schemas.common import Status, StatusValue, UnverifiedReason
from tests.api.test_results_api import _env
from tests.core.run_case_fakes import wire

UNKNOWN = Status(value=StatusValue.UNVERIFIED, reason=UnverifiedReason.NOT_EXTRACTED)


# 못 읽은 칸에 AI가 남긴 글자 (사람 값과 다른 번호 조각). 이어 돈 뒤 이 글자가 남으면 안 된다
AI_TEXT = {"application_number": "10-2099-00000?1", "dispatch_number": "9-5-2099-0000000?1"}


def _unread(monkeypatch, *fields):
    """F1이 그 번호 칸을 못 읽은 것처럼 한다 (깨진 글자 + 쪽). read_oa를 부른 횟수를 센다."""
    oa = wire(monkeypatch)
    oa = oa.model_copy(
        update={
            f: getattr(oa, f).model_copy(
                update={"status": UNKNOWN, "value": None, "raw_text": AI_TEXT[f], "page": 1}
            )
            for f in fields
        }
    )
    calls = []

    def fake(*a, **k):
        calls.append(1)
        return oa

    monkeypatch.setattr(read_oa_mod, "read_oa", fake)
    return calls


@pytest.fixture
def waiting_app(tmp_path, monkeypatch):
    calls = _unread(monkeypatch, "application_number")
    env = _env(tmp_path)
    created = env.upload()
    st = env.client.get(f"/runs/{created['run_id']}").json()
    assert (st["state"], st["waiting_for"]) == ("waiting_for_human", "application_number")
    return env, created, calls


def test_human_inputs_api_출원번호를_넣으면_같은_실행이_이어_돌아_끝난다(waiting_app):
    env, created, calls = waiting_app

    res = env.client.patch(
        f"/cases/{created['case_id']}", json={"application_number": "10-2099-0000001"}
    )

    assert res.status_code == 200, res.text
    assert res.json() == {
        "case_id": created["case_id"],
        "oa_id": created["oa_id"],
        "run_id": created["run_id"],  # 새 실행이 아니라 같은 실행
    }
    st = env.client.get(f"/runs/{created['run_id']}").json()
    assert st["state"] == "succeeded" and st["waiting_for"] is None
    assert calls == [1]  # F1 모델(read_oa)은 다시 부르지 않았다
    oa = env.client.get(f"/oas/{created['oa_id']}/oa-result").json()
    assert oa["run_id"] == created["run_id"]
    app = oa["result"]["application_number"]
    # 사람이 넣은 값: 숫자로 맞추고, AI가 원문에서 읽은 값과 확인 글로 구분한다
    assert app["value"] == "1020990000001"
    assert app["status"]["value"] == "confirmed" and app["status"]["checked"] == HUMAN_CHECKED
    # AI가 읽은 깨진 글자·원문 쪽이 "확인됨"으로 남지 않는다 (화면·의견서가 raw_text를 먼저 읽음)
    assert app["raw_text"] == "1020990000001" and app["page"] is None
    # 이어 돈 뒤 F3·F4 결과도 같은 실행에서 열린다
    assert env.get(created["oa_id"], "drafts").json()["run_id"] == created["run_id"]
    assert env.human.numbers_for_run(created["run_id"]) == {"application_number": "1020990000001"}


def test_human_inputs_api_출원번호_꼴이_아니면_422이고_실행은_그대로_기다린다(waiting_app):
    env, created, _ = waiting_app
    res = env.client.patch(f"/cases/{created['case_id']}", json={"application_number": "123"})
    assert (res.status_code, res.json()["code"]) == (422, "invalid_application_number")
    assert env.client.get(f"/runs/{created['run_id']}").json()["state"] == "waiting_for_human"
    assert env.human.numbers_for_run(created["run_id"]) == {}


def test_human_inputs_api_없는_사건이면_404(waiting_app):
    env, _, _ = waiting_app
    res = env.client.patch("/cases/c_없음", json={"application_number": "10-2099-0000001"})
    assert (res.status_code, res.json()["code"]) == (404, "case_not_found")


def test_human_inputs_api_번호를_기다리지_않으면_409(tmp_path, monkeypatch):
    wire(monkeypatch)
    env = _env(tmp_path)
    created = env.upload()  # 번호를 다 읽어 끝까지 돈다
    res = env.client.patch(
        f"/cases/{created['case_id']}", json={"application_number": "10-2099-0000001"}
    )
    assert (res.status_code, res.json()["code"]) == (409, "not_waiting")
    res = env.client.patch(
        f"/oas/{created['oa_id']}", json={"dispatch_number": "9-5-2099-000000001"}
    )
    assert (res.status_code, res.json()["code"]) == (409, "not_waiting")


def test_human_inputs_api_발송번호를_넣으면_이어_돈다(tmp_path, monkeypatch):
    _unread(monkeypatch, "dispatch_number")
    env = _env(tmp_path)
    created = env.upload()
    assert env.client.get(f"/runs/{created['run_id']}").json()["waiting_for"] == "dispatch_number"

    bad = env.client.patch(f"/oas/{created['oa_id']}", json={"dispatch_number": "10-2099-0000001"})
    assert (bad.status_code, bad.json()["code"]) == (422, "invalid_dispatch_number")
    res = env.client.patch(
        f"/oas/{created['oa_id']}", json={"dispatch_number": "9-5-2099-000000001"}
    )

    assert res.status_code == 200, res.text
    assert env.client.get(f"/runs/{created['run_id']}").json()["state"] == "succeeded"
    disp = env.client.get(f"/oas/{created['oa_id']}/oa-result").json()["result"]["dispatch_number"]
    assert disp["value"] == "952099000000001" and disp["status"]["checked"] == HUMAN_CHECKED


def test_human_inputs_api_둘_다_못_읽으면_하나씩_넣고_차례로_이어_돈다(tmp_path, monkeypatch):
    _unread(monkeypatch, "application_number", "dispatch_number")
    env = _env(tmp_path)
    created = env.upload()
    run = f"/runs/{created['run_id']}"

    first = env.client.patch(
        f"/cases/{created['case_id']}", json={"application_number": "1020990000001"}
    )
    assert first.status_code == 200, first.text
    # 출원번호는 채웠고, 이번에는 발송번호를 기다리며 다시 멈춘다
    assert env.client.get(run).json()["waiting_for"] == "dispatch_number"
    second = env.client.patch(
        f"/oas/{created['oa_id']}", json={"dispatch_number": "952099000000001"}
    )
    assert second.status_code == 200, second.text

    assert env.client.get(run).json()["state"] == "succeeded"
    result = env.client.get(f"/oas/{created['oa_id']}/oa-result").json()["result"]
    assert result["application_number"]["value"] == "1020990000001"
    assert result["dispatch_number"]["value"] == "952099000000001"


def test_human_inputs_api_confirmation_맞아요는_지금_보이는_정리의_실행에_남는다(
    tmp_path, monkeypatch
):
    wire(monkeypatch)
    env = _env(tmp_path)
    created = env.upload()
    url = f"/oas/{created['oa_id']}/oa-result/confirmation"

    before = env.client.get(url).json()
    assert before == {"oa_id": created["oa_id"], "run_id": created["run_id"], "confirmed_at": None}
    put = env.client.put(url, json={"run_id": created["run_id"]})
    assert put.status_code == 200 and put.json()["confirmed_at"] is not None
    assert env.client.get(url).json()["confirmed_at"] == put.json()["confirmed_at"]

    # 다시 돌리면 새 정리가 보이고, 옛 실행을 확인한 것은 세지 않는다
    rerun = env.client.post(f"/oas/{created['oa_id']}/runs").json()["run_id"]
    after = env.client.get(url).json()
    assert after["run_id"] == rerun and after["confirmed_at"] is None


def test_human_inputs_api_confirmation_옛_정리를_보고_누른_맞아요는_409이고_확인이_안_남는다(
    tmp_path, monkeypatch
):
    wire(monkeypatch)
    env = _env(tmp_path)
    created = env.upload()
    url = f"/oas/{created['oa_id']}/oa-result/confirmation"
    old_run = created["run_id"]

    # 화면이 옛 정리를 보는 사이 다시 돌려 새 정리가 보이게 된다
    rerun = env.client.post(f"/oas/{created['oa_id']}/runs").json()["run_id"]
    stale = env.client.put(url, json={"run_id": old_run})
    assert (stale.status_code, stale.json()["code"]) == (409, "stale_result")
    assert env.client.get(url).json() == {
        "oa_id": created["oa_id"],
        "run_id": rerun,
        "confirmed_at": None,
    }
    # 옛 정리의 실행에도 확인이 남지 않는다 (GET은 지금 보이는 실행만 본다)
    assert env.human.confirmed_at(created["oa_id"], old_run) is None
    # 본문이 없으면 422
    assert env.client.put(url).status_code == 422
    # 새 정리의 run_id로는 남는다
    assert env.client.put(url, json={"run_id": rerun}).status_code == 200


def test_human_inputs_api_confirmation_맞아요는_정리_전이면_404(tmp_path, monkeypatch):
    wire(monkeypatch)
    env = _env(tmp_path)
    env.launch_enabled = False
    created = env.upload()
    url = f"/oas/{created['oa_id']}/oa-result/confirmation"
    assert env.client.put(url, json={"run_id": "run_x"}).json()["code"] == "result_not_ready"
    assert env.client.get("/oas/oa_없음/oa-result/confirmation").json()["code"] == "oa_not_found"


def test_human_inputs_api_번호를_넣으면_바로_대기로_바뀌고_두_번째는_409(waiting_app):
    # 리뷰 막음: 실행기가 잡기 전에도 사람 기다림으로 남지 않고, 나중 번호가 몰래 이기지 않는다
    env, created, _ = waiting_app
    env.launch_enabled = False  # 실행기가 아직 안 잡은 순간
    url = f"/cases/{created['case_id']}"

    first = env.client.patch(url, json={"application_number": "10-2099-0000001"})
    st = env.client.get(f"/runs/{created['run_id']}").json()
    second = env.client.patch(url, json={"application_number": "10-2099-0000002"})

    assert first.status_code == 200
    assert (st["state"], st["waiting_for"]) == ("queued", None)
    assert (second.status_code, second.json()["code"]) == (409, "not_waiting")
    assert env.human.numbers_for_run(created["run_id"]) == {"application_number": "1020990000001"}
    # 실행기가 잡으면 처음 넣은 번호로 이어 돈다
    env.executor.execute(created["run_id"], created["oa_id"])
    oa = env.client.get(f"/oas/{created['oa_id']}/oa-result").json()["result"]
    assert oa["application_number"]["value"] == "1020990000001"


@pytest.mark.parametrize(
    ("url_of", "body", "kind"),
    [
        (
            lambda c: f"/cases/{c['case_id']}",
            {"application_number": "10-2099-0000001"},
            "application_number",
        ),
        (
            lambda c: f"/oas/{c['oa_id']}",
            {"dispatch_number": "9-5-2099-000000001"},
            "dispatch_number",
        ),
    ],
)
def test_human_inputs_api_번호_기록_저장이_실패하면_500이고_다시_기다린다(
    tmp_path, monkeypatch, url_of, body, kind
):
    # #287: 기록 저장이 실패해도 실행이 번호 없이 queued로 남아 그 OA를 막지 않는다
    _unread(monkeypatch, kind)
    env = _env(tmp_path)
    created = env.upload()
    real_add = env.human.add

    def boom(*a, **k):
        raise RuntimeError("DB 쓰기 실패")

    monkeypatch.setattr(env.human, "add", boom)
    failed = env.client.patch(url_of(created), json=body)

    assert failed.status_code == 500
    assert failed.json()["code"] == "human_input_not_saved" and failed.json()["message"]
    st = env.client.get(f"/runs/{created['run_id']}").json()
    assert (st["state"], st["waiting_for"]) == ("waiting_for_human", kind)
    assert env.human.numbers_for_run(created["run_id"]) == {}

    # 저장이 다시 되면 다음 번호 입력은 정상으로 받아 이어 돈다
    monkeypatch.setattr(env.human, "add", real_add)
    again = env.client.patch(url_of(created), json=body)
    assert again.status_code == 200, again.text
    assert env.client.get(f"/runs/{created['run_id']}").json()["state"] == "succeeded"


def _fail_add_then(env, monkeypatch, on_revert):
    """번호 기록 저장을 실패시키고, 되돌리기(→ waiting) 때 on_revert를 부른다."""

    def boom(*a, **k):
        raise RuntimeError("DB 쓰기 실패")

    monkeypatch.setattr(env.human, "add", boom)
    real = env.runs.transition

    def transition(run_id, new, **k):
        if new.value == "waiting_for_human":
            on_revert(run_id)
        return real(run_id, new, **k)

    monkeypatch.setattr(env.runs, "transition", transition)


def test_human_inputs_api_되돌리기도_실패하면_500이고_로그를_남긴다(
    waiting_app, monkeypatch, caplog
):
    # 리뷰 고칠 것: DB가 끊기면 되돌리기도 실패한다. 조용히 넘기지 않고 같은 500 + 로그
    env, created, _ = waiting_app

    def revert_fails(run_id):
        raise ConnectionError("DB 끊김")

    _fail_add_then(env, monkeypatch, revert_fails)
    res = env.client.patch(
        f"/cases/{created['case_id']}", json={"application_number": "10-2099-0000001"}
    )

    assert (res.status_code, res.json()["code"]) == (500, "human_input_not_saved")
    assert "되돌리기도 실패" in caplog.text and created["run_id"] in caplog.text


def test_human_inputs_api_그_사이_취소됐으면_취소로_두고_500(waiting_app, monkeypatch):
    env, created, _ = waiting_app

    def cancelled_meanwhile(run_id):
        env.client.post(f"/runs/{run_id}/cancel")

    _fail_add_then(env, monkeypatch, cancelled_meanwhile)
    res = env.client.patch(
        f"/cases/{created['case_id']}", json={"application_number": "10-2099-0000001"}
    )

    assert (res.status_code, res.json()["code"]) == (500, "human_input_not_saved")
    assert env.client.get(f"/runs/{created['run_id']}").json()["state"] == "cancelled"
