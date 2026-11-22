"""F3·F4 결과 조회 API (이슈 #191 T3). 확인: uv run pytest tests/api -k results_api

진짜 실행기(RunCaseExecutor) + 메모리 저장소 + 기록된 응답. 네트워크·키·DB 없음.
launcher는 그 자리에서 바로 돈다 (진짜 앱은 백그라운드 스레드).
"""

import pytest

from patent_ai.core.agents.orchestrator import CaseInput
from tests.core.run_case_app import RunCaseApp
from tests.core.run_case_fakes import fake_ctx, texts, wire, wire_broken_pdf

NAMES = ("units", "comparisons", "clarity-reviews", "legal-evidence", "directions", "drafts")


class _Inputs:
    """메모리 사건 저장소에는 파일 경로가 없어 실행 입력을 지어 준다 (PDF 읽기는 바꿔 끼움)."""

    def __init__(self, tmp_path, with_texts):
        self.tmp_path, self.with_texts = tmp_path, with_texts

    def case_input(self, oa_id):
        return CaseInput(
            case_id="c_1",
            oa_document=self.tmp_path / "oa.pdf",
            oa_document_id="d_1",
            texts=texts() if self.with_texts else None,
        )


def _env(tmp_path, with_texts=True) -> RunCaseApp:
    return RunCaseApp(
        tmp_path, make_inputs=lambda cases: _Inputs(tmp_path, with_texts), make_ctx=fake_ctx
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    wire(monkeypatch)
    return _env(tmp_path)


def test_results_api_실행이_끝나면_F3_F4_결과가_같은_실행에서_열린다(env):
    created = env.upload()
    oa_id, run_id = created["oa_id"], created["run_id"]
    assert env.client.get(f"/runs/{run_id}").json()["state"] == "succeeded"
    got = {n: env.get(oa_id, n) for n in NAMES}
    assert {n: r.status_code for n, r in got.items()} == dict.fromkeys(NAMES, 200)
    body = {n: r.json() for n, r in got.items()}
    # 모든 결과가 OA 정리와 같은 실행에서 나온다
    oa_result = env.client.get(f"/oas/{oa_id}/oa-result").json()
    assert {b["run_id"] for b in body.values()} == {oa_result["run_id"]} == {run_id}
    for n in ("units", "comparisons", "clarity-reviews", "directions"):
        assert body[n]["result"] and body[n]["empty_reason"] is None, n
    assert body["drafts"]["result"] is not None and body["drafts"]["legality_notice"]
    assert body["directions"]["rank_notice"]


def test_results_api_넘긴_F2는_빈_목록과_넘긴_이유(env):
    oa_id = env.upload()["oa_id"]
    legal = env.get(oa_id, "legal-evidence")
    assert legal.status_code == 200
    assert legal.json()["result"] == []
    assert legal.json()["empty_reason"].startswith("넘김: tool_missing")


def test_results_api_청구항_판을_못_찾으면_F3_F4는_빈_목록과_input_unverified(
    tmp_path, monkeypatch
):
    wire(monkeypatch)
    env = _env(tmp_path, with_texts=False)
    oa_id = env.upload()["oa_id"]
    for n in ("units", "comparisons", "clarity-reviews", "directions"):
        r = env.get(oa_id, n).json()
        assert r["result"] == [] and r["empty_reason"].startswith("넘김: input_unverified"), n
    drafts = env.get(oa_id, "drafts").json()
    assert drafts["result"] is None and drafts["empty_reason"].startswith("넘김: input_unverified")
    assert drafts["held_units"] == []


def test_results_api_실행_전이면_404_result_not_ready(env):
    env.launch_enabled = False
    oa_id = env.upload()["oa_id"]
    for n in NAMES:
        r = env.get(oa_id, n)
        assert r.status_code == 404 and r.json()["code"] == "result_not_ready", n


def test_results_api_실패한_실행의_결과는_주지_않는다(tmp_path, monkeypatch):
    wire(monkeypatch)
    wire_broken_pdf(monkeypatch, secret="원문")
    env = _env(tmp_path)
    created = env.upload()
    run = env.client.get(f"/runs/{created['run_id']}").json()
    assert run["state"] == "failed" and "원문" not in run["error"]["message"]
    for n in NAMES:
        assert env.get(created["oa_id"], n).status_code == 404, n


def test_results_api_없는_OA면_404_oa_not_found(env):
    for n in NAMES:
        r = env.get("oa_없음", n)
        assert r.status_code == 404 and r.json()["code"] == "oa_not_found", n


def test_results_api_저장한_결과를_못_읽으면_500이_아니라_빈_결과와_이유(env):
    # M3에서 F3·F4 결과 칸이 바뀌어 옛 줄을 못 읽는 경우를 흉내 낸다 (#206 리뷰)
    created = env.upload()
    oa_id, run_id = created["oa_id"], created["run_id"]
    for kind in ("f3", "f4"):
        oa, _ = env.steps._rows[(run_id, kind)]
        env.steps._rows[(run_id, kind)] = (oa, {"옛_칸": 1})
    for n in ("units", "comparisons", "clarity-reviews", "directions", "drafts"):
        r = env.get(oa_id, n)
        assert r.status_code == 200, n
        body = r.json()
        assert body["result"] in ([], None), n
        assert body["empty_reason"].startswith("확인되지 않음: 저장된 결과를 읽지 못함"), n
