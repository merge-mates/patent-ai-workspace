# ruff: noqa: E501
"""실제 앱 흐름(POST /cases → F1 → F3 → F2 → F4)을 구독으로 한 건 돌리고 F4 입력·결과를 저장한다.

코드 스냅숏 폴더에서 돈다. API 키가 없어야 하고, DB는 실험 전용이어야 한다.
"""

import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
key, out, dsn = sys.argv[1], Path(sys.argv[2]), os.environ["DATABASE_URL"]
assert dsn.endswith("/patent_ai_e2e_opinion"), "실험 전용 DB만 쓴다"
for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_BASE_URL"):
    assert k not in os.environ, f"{k}가 있으면 유료 호출이 나갈 수 있다"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run as R  # noqa: E402

from patent_ai.api import deps  # noqa: E402
from patent_ai.core.agents import tools_f4  # noqa: E402
from patent_ai.core.llm.limits import CallBudget, RunContext  # noqa: E402
from patent_ai.core.llm.transport import TransportError, TransportResponse  # noqa: E402
from patent_ai.core.runs.step_log_pg import PostgresCallRecorder  # noqa: E402


class SubTransport:
    """구독 전송층. is_real 표시를 안 해 앱이 진짜로 다뤄 상한·파일 캐시가 켜진다."""

    def complete(self, *, step, model, prompt, effort, max_tokens):
        try:
            text, u = R.ask(model, effort, prompt)
        except RuntimeError as e:
            raise TransportError(str(e), False) from e
        print(step, flush=True)
        n = (
            u["input_tokens"]
            + u.get("cache_creation_input_tokens", 0)
            + u.get("cache_read_input_tokens", 0)
        )
        return TransportResponse(text, n, u["output_tokens"], "end_turn")

    def converse(self, **_):
        raise RuntimeError("tool use 호출은 쓰지 않는다")


def main():
    out.mkdir(parents=True, exist_ok=True)
    from sqlalchemy.orm import sessionmaker

    deps._new_run_context = lambda run_id: RunContext(
        run_id=run_id,
        budget=CallBudget(),
        recorder=PostgresCallRecorder(sessionmaker(deps._engine())),
        transport=SubTransport(),
    )
    orig = tools_f4.run_f4

    def saved(inp, *, ctx, **kw):
        (out / "f4_input.json").write_text(inp.model_dump_json(), encoding="utf-8")
        return orig(inp, ctx=ctx, **kw)

    tools_f4.run_f4 = saved
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
    body = r.json()
    if r.status_code != 200:
        sys.exit(f"올리기 실패 {r.status_code} {body}")
    run = body["run_id"]
    st = deps.get_run_status_store()
    f1 = deps.get_oa_result_store().oa_result_of_run(run)
    items = [("f1", f1)] + [
        (k, deps.get_step_result_store().step_result(run, k)) for k in ("f3", "f2", "f4")
    ]
    for name, o in items:
        if o is not None:
            (out / f"{name}.json").write_text(o.model_dump_json(indent=1), encoding="utf-8")
    s = {
        "state": str(st.get_status(run).state),
        "waiting_for": str(getattr(st.get_status(run), "waiting_for", None)),
    }
    s["skipped"] = [(x.step, x.reason) for x in st.skipped_steps(run)]
    (out / "summary.json").write_text(json.dumps(s, ensure_ascii=False))
    print("DONE", s)


main()
