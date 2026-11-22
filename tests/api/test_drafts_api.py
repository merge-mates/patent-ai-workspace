"""사람이 초안을 고치는 API PATCH /drafts/{draft_id} (이슈 #304 T1).

확인: uv run pytest tests/api -k drafts_api
진짜 실행기 + 메모리 저장소 + 가짜 응답 (네트워크·키·DB 없음).
"""

import pytest

from tests.api.test_results_api import _env
from tests.core.run_case_fakes import wire, wire_broken_pdf


@pytest.fixture
def env(tmp_path, monkeypatch):
    oa = wire(monkeypatch)
    # 진짜 read_oa처럼 OA 정리에 그 OA의 id를 넣는다 (지어낸 정리는 늘 oa_1이라
    # draft_id = dr:<oa_id>가 진짜 OA를 가리키지 않는다)
    monkeypatch.setattr(
        "patent_ai.core.f1_oa_reader.read_oa.read_oa",
        lambda pages, document_id, oa_id, *a, **k: oa.model_copy(update={"oa_id": oa_id}),
    )
    return _env(tmp_path)


def _drafts(env, oa_id):
    body = env.get(oa_id, "drafts").json()
    assert body["result"] is not None, body
    return body["result"]


def _section(drafts, key):
    return next(s for s in drafts["opinion"] if s["key"] == key)


def _claim(drafts, no):
    return next(c for c in drafts["claims"] if c["claim"] == no)


def test_drafts_api_의견서_칸을_고치면_AI_원문은_남고_human_edited(env):
    oa_id = env.upload()["oa_id"]
    before = _drafts(env, oa_id)
    ai = _section(before, "closing")["ai_text"]

    r = env.client.patch(
        f"/drafts/{before['draft_id']}", json={"section": "closing", "text": "사람이 고친 마무리"}
    )
    assert r.status_code == 200, r.text
    got = _section(r.json(), "closing")
    assert got["ai_text"] == ai
    assert got["human_text"] == "사람이 고친 마무리" and got["origin"] == "human_edited"
    assert r.json()["origin"] == "human_edited"  # 고친 칸이 있으면 초안 맨 위도
    # 다른 칸은 그대로
    assert _section(r.json(), "points") == _section(before, "points")


def test_drafts_api_고친_글은_다시_열어도_남는다(env):
    oa_id = env.upload()["oa_id"]
    draft_id = _drafts(env, oa_id)["draft_id"]
    env.client.patch(f"/drafts/{draft_id}", json={"section": "response", "text": "고친 대응"})
    env.client.patch(f"/drafts/{draft_id}", json={"claim": 1, "text": "1. 고친 청구항"})

    again = _drafts(env, oa_id)  # 다시 열기
    assert _section(again, "response")["human_text"] == "고친 대응"
    assert _claim(again, 1)["human_text"] == "1. 고친 청구항"
    assert _claim(again, 1)["origin"] == "human_edited"
    assert again["origin"] == "human_edited"


def test_drafts_api_보정_청구항을_고치면_before와_AI_원문은_그대로(env):
    oa_id = env.upload()["oa_id"]
    before = _claim(_drafts(env, oa_id), 2)
    r = env.client.patch(f"/drafts/dr:{oa_id}", json={"claim": 2, "text": "2. 고친 보정"})
    assert r.status_code == 200, r.text
    got = _claim(r.json(), 2)
    assert got["before"] == before["before"] and got["ai_text"] == before["ai_text"]
    assert got["human_text"] == "2. 고친 보정"


def test_drafts_api_AI_원문과_같은_글을_보내면_고친_것을_되돌린다(env):
    oa_id = env.upload()["oa_id"]
    d = _drafts(env, oa_id)
    ai = _section(d, "closing")["ai_text"]
    env.client.patch(f"/drafts/{d['draft_id']}", json={"section": "closing", "text": "고침"})
    r = env.client.patch(f"/drafts/{d['draft_id']}", json={"section": "closing", "text": ai})
    got = _section(r.json(), "closing")
    assert got["human_text"] is None and got["origin"] == "ai_generated"
    assert r.json()["origin"] == "ai_generated"
    assert _drafts(env, oa_id)["origin"] == "ai_generated"


def test_drafts_api_없는_초안이면_404_draft_not_found(env):
    oa_id = env.upload()["oa_id"]
    assert _drafts(env, oa_id)["draft_id"] == f"dr:{oa_id}"
    for draft_id in ("dr:oa_없음", "없는꼴", f"dr:{oa_id}x"):
        r = env.client.patch(f"/drafts/{draft_id}", json={"section": "closing", "text": "x"})
        assert r.status_code == 404 and r.json()["code"] == "draft_not_found", draft_id


def test_drafts_api_보여_줄_결과가_없으면_404_draft_not_found(env, monkeypatch):
    # 실행이 실패해 보여 줄 초안이 없다 (실행 전·실행 중이면 위 409)
    wire_broken_pdf(monkeypatch, secret="원문")
    oa_id = env.upload()["oa_id"]
    r = env.client.patch(f"/drafts/dr:{oa_id}", json={"section": "closing", "text": "x"})
    assert r.status_code == 404 and r.json()["code"] == "draft_not_found"


def test_drafts_api_없는_칸_없는_청구항은_422(env):
    oa_id = env.upload()["oa_id"]
    r = env.client.patch(f"/drafts/dr:{oa_id}", json={"claim": 99, "text": "x"})
    assert r.status_code == 422 and r.json()["code"] == "claim_not_editable"
    r = env.client.patch(f"/drafts/dr:{oa_id}", json={"section": "없는칸", "text": "x"})
    assert r.status_code == 422 and r.json()["code"] == "invalid_draft_edit"


def test_drafts_api_칸과_청구항_중_하나만_그리고_빈_글은_422(env):
    oa_id = env.upload()["oa_id"]
    bad = (
        {"text": "x"},
        {"section": "closing", "claim": 1, "text": "x"},
        {"section": "closing", "text": "   "},
    )
    for body in bad:
        r = env.client.patch(f"/drafts/dr:{oa_id}", json=body)
        assert r.status_code == 422 and r.json()["code"] == "invalid_draft_edit", body
    r = env.client.patch(f"/drafts/dr:{oa_id}", json={"section": "closing"})  # text 없음
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    assert _drafts(env, oa_id)["origin"] == "ai_generated"  # 아무것도 저장되지 않음


def test_drafts_api_보류된_청구항은_고칠_수_없다(env):
    oa_id = env.upload()["oa_id"]
    run_id = env.get(oa_id, "drafts").json()["run_id"]
    # 청구항 2를 보류(확신 낮음)로 바꿔 둔다
    oa, body = env.steps._rows[(run_id, "f4")]
    c2 = next(c for c in body["drafts"]["claims"] if c["claim"] == 2)
    c2.update(ai_text=None, spec_basis=[], held_reason="방향을 고르면 초안을 만듭니다")
    env.steps._rows[(run_id, "f4")] = (oa, body)

    r = env.client.patch(f"/drafts/dr:{oa_id}", json={"claim": 2, "text": "2. 사람이 씀"})
    assert r.status_code == 422 and r.json()["code"] == "claim_not_editable"
    assert _claim(_drafts(env, oa_id), 2)["human_text"] is None


def test_drafts_api_진행_중인_실행이_있으면_409_run_in_progress(env):
    # 그 실행이 끝나면 새 초안이 보여 지금 고친 글이 사라지므로 받지 않는다 (#305 리뷰)
    oa_id = env.upload()["oa_id"]
    env.launch_enabled = False
    assert env.client.post(f"/oas/{oa_id}/runs").status_code == 200  # queued로 남는다
    r = env.client.patch(f"/drafts/dr:{oa_id}", json={"section": "closing", "text": "고침"})
    assert r.status_code == 409 and r.json()["code"] == "run_in_progress"
    assert _section(_drafts(env, oa_id), "closing")["human_text"] is None  # 저장 안 됨
