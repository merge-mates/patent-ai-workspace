"""사건 전체 검사 API GET /oas/{oa_id}/case-check (이슈 #304 T2).

확인: uv run pytest tests/api -k case_check
진짜 실행기 + 메모리 저장소 + 가짜 응답 (네트워크·키·DB 없음).
"""

import pytest

from patent_ai.core.schemas.oa_result import OAResult
from tests.api.test_results_api import _env
from tests.core.run_case_fakes import wire


@pytest.fixture
def env(tmp_path, monkeypatch):
    wire(monkeypatch)
    return _env(tmp_path)


def _items(body):
    return {i["name"]: i for i in body["items"]}


def test_case_check_api_다_다룬_사건은_지원_안_하는_거절이유가_없다(env):
    created = env.upload()
    r = env.get(created["oa_id"], "case-check")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["oa_id"] == created["oa_id"] and body["run_id"] == created["run_id"]
    assert body["unsupported_rejections"] == []
    items = _items(body)
    assert items["지원 안 하는 거절이유"]["result"] == "ok"
    assert items["같은 청구항을 고친 묶음"]["result"] == "ok"


def test_case_check_api_아직_검사하지_않는_규칙은_ok로_지어내지_않는다(env):
    body = env.get(env.upload()["oa_id"], "case-check").json()
    items = _items(body)
    for name in ("독립항 보정이 종속항에 번짐", "삭제 뒤 인용 번호", '"또는"형 종속항 가지'):
        assert items[name]["result"] == "warn", name
        assert items[name]["detail"].startswith("확인되지 않음"), name


def test_case_check_api_지원_안_하는_거절이유는_번호와_warn(env):
    created = env.upload()
    oa_id, run_id = created["oa_id"], created["run_id"]
    # 저장된 OA 정리에서 거절이유 2를 지원 안 함으로 바꿔 둔다
    saved = env.oa_results.latest_visible_oa_result(oa_id).result
    data = saved.model_dump(mode="json")
    rej = next(x for x in data["rejections"] if x["no"] == 2)
    rej["supported"] = False
    rej["flags"] = sorted({*rej["flags"], "needs_human_review"})
    data["claim_rows"] = [c for c in data["claim_rows"] if c["rejection"] != 2]
    env.oa_results.save_oa_result(oa_id, run_id, OAResult.model_validate(data))

    body = env.get(oa_id, "case-check").json()
    assert body["unsupported_rejections"] == [2]
    item = _items(body)["지원 안 하는 거절이유"]
    assert item["result"] == "warn" and "2" in item["detail"]


def test_case_check_api_겹친_보정_청구항은_warn(env):
    created = env.upload()
    oa_id, run_id = created["oa_id"], created["run_id"]
    oa, f4 = env.steps._rows[(run_id, "f4")]
    f4["amendment_overlaps"] = [{"claim": 1, "kept_unit": "u_1", "dropped_unit": "u_2"}]
    env.steps._rows[(run_id, "f4")] = (oa, f4)

    item = _items(env.get(oa_id, "case-check").json())["같은 청구항을 고친 묶음"]
    assert item["result"] == "warn" and "청구항 1" in item["detail"]


def test_case_check_api_F4를_넘기면_겹침은_확인되지_않음(tmp_path, monkeypatch):
    wire(monkeypatch)
    env = _env(tmp_path, with_texts=False)  # 청구항 판이 없어 F3·F4를 넘긴다
    body = env.get(env.upload()["oa_id"], "case-check").json()
    item = _items(body)["같은 청구항을 고친 묶음"]
    assert item["result"] == "warn" and item["detail"].startswith("확인되지 않음")


def test_case_check_api_결과_전이면_404_없는_OA면_404(env):
    env.launch_enabled = False
    oa_id = env.upload()["oa_id"]
    r = env.get(oa_id, "case-check")
    assert r.status_code == 404 and r.json()["code"] == "result_not_ready"
    r = env.get("oa_없음", "case-check")
    assert r.status_code == 404 and r.json()["code"] == "oa_not_found"
