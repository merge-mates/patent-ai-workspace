# ruff: noqa: E501
"""앱 F4 바깥 보정안 모드(amendment_enabled false, 재아 #349 브랜치)에 E 보정안을 넣어 의견서를 만든다 (구독).

쓰는 법: app_external.py <사건 폴더(f4_input.json·plan.json)> <회차> <결과 json 경로>
F4 입력의 F3·F2 결과는 그대로 쓰고, external_amendment만 E 1번 안으로 채운다. 결과는 의견서 칸 이름 → 글.
"""

import dataclasses
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
assert not any(k.endswith("_API_KEY") for k in os.environ), "키가 있으면 유료 호출이 나갈 수 있다"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run as R  # noqa: E402

from patent_ai.core.f4_response_draft.config import load_f4_options  # noqa: E402
from patent_ai.core.f4_response_draft.inputs import F4Input  # noqa: E402
from patent_ai.core.f4_response_draft.plan_check import to_external  # noqa: E402
from patent_ai.core.f4_response_draft.run import run_f4  # noqa: E402
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext  # noqa: E402
from patent_ai.core.llm.transport import TransportError, TransportResponse  # noqa: E402


class Sub:
    def complete(self, *, step, model, prompt, effort, max_tokens, system=None):
        try:
            text, u = R.ask(model, effort, prompt, system)
        except RuntimeError as e:
            raise TransportError(str(e), False) from e
        n = (
            u["input_tokens"]
            + u.get("cache_creation_input_tokens", 0)
            + u.get("cache_read_input_tokens", 0)
        )
        return TransportResponse(text, n, u["output_tokens"], "end_turn")


folder, rep, dest = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
if dest.exists():
    sys.exit(0)
base = F4Input.model_validate_json((folder / "f4_input.json").read_text())
plan = json.loads((folder / "plan.json").read_text())
old = {c.claim: c.text for c in base.claims_text}
inp = base.model_copy(
    update={"external_amendment": to_external(old, plan["amended"], source="E 1번 안")}
)
options = dataclasses.replace(load_f4_options(), amendment_enabled=False)
ctx = RunContext(
    f"appext-{folder.name}-{rep}", CallBudget(), MemoryRecorder(), transport=Sub(), cache=False
)
out = run_f4(inp, ctx=ctx, options=options)
if out.drafts is None:
    sys.exit(f"{folder}: 의견서가 없음 (모두 보류) {out.held_units}")
sections = {s.title: s.ai_text for s in out.drafts.opinion if s.key.value != "case_info"}
dest.write_text(json.dumps(sections, ensure_ascii=False, indent=1))
print("DONE", folder, rep, "호출", len(ctx.recorder.records), "보류", out.held_units)
