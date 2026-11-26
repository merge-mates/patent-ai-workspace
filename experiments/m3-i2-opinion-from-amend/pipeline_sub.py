# ruff: noqa: E501
"""앱 흐름(F1 → F3 → F2 → F4)을 구독으로 한 건 돌린다. 둘째 인자 뒤에 plan.json을 주면 F3만 보정 뒤 청구항으로 대비한다.

코드 스냅숏 폴더(config/f3.yaml search.impl = bm25)에서 돈다. API 키가 없어야 하고, DB는 실험 전용이어야 한다.
같은 캐시 폴더를 쓰므로 F1과 바뀌지 않은 청구항의 F3 호출은 두 판에서 같은 답을 쓴다.
"""

import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
key, out = sys.argv[1], Path(sys.argv[2])
plan_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None
assert "/patent_ai_e2e_sub_" in os.environ["DATABASE_URL"], "실험 전용 DB만 쓴다"
assert not any(k.endswith("_API_KEY") for k in os.environ), "키가 있으면 유료 호출이 나갈 수 있다"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run as R  # noqa: E402

from patent_ai.api import deps  # noqa: E402
from patent_ai.core.agents import orchestrator  # noqa: E402
from patent_ai.core.f4_response_draft import run as f4_run  # noqa: E402
from patent_ai.core.llm.cache import FileCache  # noqa: E402
from patent_ai.core.llm.limits import CallBudget, RunContext  # noqa: E402
from patent_ai.core.llm.transport import TransportError, TransportResponse  # noqa: E402
from patent_ai.core.runs.step_log_pg import PostgresCallRecorder  # noqa: E402


class Sub:
    def complete(self, *, step, model, prompt, effort, max_tokens):
        try:
            text, u = R.ask(model, effort, prompt)
        except RuntimeError as e:
            raise TransportError(str(e), False) from e
        n = (
            u["input_tokens"]
            + u.get("cache_creation_input_tokens", 0)
            + u.get("cache_read_input_tokens", 0)
        )
        return TransportResponse(text, n, u["output_tokens"], "end_turn")

    def converse(self, **_):
        raise RuntimeError("tool use 호출은 쓰지 않는다")

    def embed(self, **_):
        raise RuntimeError("임베딩은 쓰지 않는다 (bm25)")


def main():
    from sqlalchemy.orm import sessionmaker

    out.mkdir(parents=True, exist_ok=True)
    cache = FileCache(out.parent / "llm_cache")
    deps._new_run_context = lambda run_id: RunContext(
        run_id=run_id,
        budget=CallBudget(),
        recorder=PostgresCallRecorder(sessionmaker(deps._engine())),
        transport=Sub(),
        cache=cache,
    )
    if plan_path:  # 판단 단위 나누기와 F3에만 보정 뒤 청구항 글을 준다 (F4는 OA 당시 글 그대로)
        plan = json.loads(plan_path.read_text())

        def amend(texts):
            if texts is None:
                return None
            claims = dict(texts.claims_at_oa)
            for q in plan["amended"]:
                if q["action"] != "delete" and q["claim"] in claims:
                    claims[q["claim"]] = q["text"]
            return texts.model_copy(update={"claims_at_oa": claims})

        for name in ("prepare_input", "f3_input"):
            orig = getattr(orchestrator, name)
            setattr(orchestrator, name, lambda r, c, t, orig=orig: orig(r, c, amend(t)))
    f4_orig = f4_run.run_f4

    def saved(inp, *, ctx, **kw):
        (out / "f4_input.json").write_text(inp.model_dump_json(), encoding="utf-8")
        return f4_orig(inp, ctx=ctx, **kw)

    f4_run.run_f4 = saved
    from fastapi.testclient import TestClient

    from patent_ai.api.main import create_app

    app = create_app()
    app.dependency_overrides[deps.get_run_launcher] = lambda: (
        lambda r, o: deps.get_run_executor().execute(r, o)
    )
    app_no, disp = key.split("_")
    (pdf,) = (Path("data/processed/cases") / app_no / disp).glob("*_OA_*.pdf")
    r = TestClient(app).post(
        "/cases", files={"file": ("oa.pdf", pdf.read_bytes(), "application/pdf")}
    )
    if r.status_code != 200:
        sys.exit(f"올리기 실패 {r.status_code} {r.json()}")
    run = r.json()["run_id"]
    st = deps.get_run_status_store()
    s = {
        "state": str(st.get_status(run).state),
        "skipped": [(x.step, x.reason) for x in st.skipped_steps(run)],
    }
    (out / "summary.json").write_text(json.dumps(s, ensure_ascii=False))
    print("DONE", s)


main()
