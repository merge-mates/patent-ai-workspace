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

    env.client.patch(f"/cases/{created['case_id']}", json={"application_number": "1020990000001"})
    # 출원번호는 채웠고, 이번에는 발송번호를 기다리며 다시 멈춘다
    assert env.client.get(run).json()["waiting_for"] == "dispatch_number"
    env.client.patch(f"/oas/{created['oa_id']}", json={"dispatch_number": "952099000000001"})

    assert env.client.get(run).json()["state"] == "succeeded"
    result = env.client.get(f"/oas/{created['oa_id']}/oa-result").json()["result"]
    assert result["application_number"]["value"] == "1020990000001"
    assert result["dispatch_number"]["value"] == "952099000000001"


def test_human_inputs_api_맞아요는_지금_보이는_정리의_실행에_남는다(tmp_path, monkeypatch):
    wire(monkeypatch)
    env = _env(tmp_path)
    created = env.upload()
    url = f"/oas/{created['oa_id']}/oa-result/confirmation"

    before = env.client.get(url).json()
    assert before == {"oa_id": created["oa_id"], "run_id": created["run_id"], "confirmed_at": None}
    put = env.client.put(url)
    assert put.status_code == 200 and put.json()["confirmed_at"] is not None
    assert env.client.get(url).json()["confirmed_at"] == put.json()["confirmed_at"]

    # 다시 돌리면 새 정리가 보이고, 옛 실행을 확인한 것은 세지 않는다
    rerun = env.client.post(f"/oas/{created['oa_id']}/runs").json()["run_id"]
    after = env.client.get(url).json()
    assert after["run_id"] == rerun and after["confirmed_at"] is None


def test_human_inputs_api_맞아요는_정리_전이면_404(tmp_path, monkeypatch):
    wire(monkeypatch)
    env = _env(tmp_path)
    env.launch_enabled = False
    created = env.upload()
    url = f"/oas/{created['oa_id']}/oa-result/confirmation"
    assert env.client.put(url).json()["code"] == "result_not_ready"
    assert env.client.get("/oas/oa_없음/oa-result/confirmation").json()["code"] == "oa_not_found"
