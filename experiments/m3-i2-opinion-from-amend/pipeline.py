# ruff: noqa: E501
"""실제 앱 흐름(POST /cases → F1 → F3 → F2 → F4)을 한 건 돌리고 F4 입력·결과를 저장한다 (유료 API).

서버 이미지 안에서 돈다. DB는 실험 전용이어야 한다. 호출 상한은 앱 설정(config/)의 것을 쓴다.
"""

import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
key, out, dsn = sys.argv[1], Path(sys.argv[2]), os.environ["DATABASE_URL"]
assert dsn.endswith("/patent_ai_e2e_opinion_api"), "실험 전용 DB만 쓴다"
assert "ANTHROPIC_BASE_URL" not in os.environ
from patent_ai.api import deps  # noqa: E402
from patent_ai.core.f4_response_draft import run as f4_run  # noqa: E402


def main():
    out.mkdir(parents=True, exist_ok=True)
    orig = f4_run.run_f4

    def saved(inp, *, ctx, **kw):
        (out / "f4_input.json").write_text(inp.model_dump_json(), encoding="utf-8")
        return orig(inp, ctx=ctx, **kw)

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
