# ruff: noqa: E501
"""앱 F4 그대로(f4)와 앱 F4에 E 보정안·점검을 붙인 것(f4_ours)의 초안을 만든다 (유료 API, 서버 이미지 안).

입력: pipeline.py가 저장한 f4_input.json, f4.json과 E 보정안 plan.json. 1회의 f4는 앱이 낸 것을 쓰고 2회는 다시 돈다.
"""

import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
from patent_ai.core.f4_response_draft import opinion as O  # noqa: E402
from patent_ai.core.f4_response_draft.config import load_f4_options  # noqa: E402
from patent_ai.core.f4_response_draft.directions import (  # noqa: E402
    f3_results,
    to_json,
    unit_variables,
)
from patent_ai.core.f4_response_draft.inputs import F4Input, legal_bundle_for  # noqa: E402
from patent_ai.core.f4_response_draft.llm_call import call_with_one_retry  # noqa: E402
from patent_ai.core.f4_response_draft.run import run_f4  # noqa: E402
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext  # noqa: E402

HERE = Path(__file__).resolve().parent
folder, rep = Path(sys.argv[1]), int(sys.argv[2])
TITLES = {
    "points": "지적 요지",
    "response": "대응과 근거",
    "amendment": "보정 설명",
    "closing": "마무리",
}


def ours(inp, plan, ctx, oa=None, before=False):
    """판단 단위마다 앱 의견서 프롬프트를 쓰되, 고른 방향 자리에 E 전략·보정안을, 끝에 점검 지시를 넣는다."""
    note = "".join(
        (HERE / f"prompts/{n}.md").read_text(encoding="utf-8") for n in ("note_amend", "note_check")
    )
    rows = [
        {
            "청구항": q["claim"],
            "종류": "삭제" if q["action"] == "delete" else "고침",
            "이유": q["reason"],
            "보정 뒤 글": q["text"] or "(삭제)",
        }
        | ({"보정 전 글": q["before"]} if before else {})
        for q in plan["amended"]
    ]
    parts = {k: [] for k in TITLES}
    for unit in sorted(inp.units, key=lambda u: (u.order, u.unit_id)):
        v = unit_variables(
            inp, unit, f3_results(inp, unit), legal_bundle_for(inp, unit), max_candidates=1
        )
        del v["max_candidates"]
        v["case_info"] = to_json(
            {
                "application_number": None,
                "dispatch_number": None,
                "notice_date": None,
                "response_due": None,
            }
        )
        v["selected"] = to_json({"name": plan["strategy"], "보정안": rows}) + "\n" + note
        if oa:  # 셋째 비교: 거절이유 자리 뒤에 OA 글자 전체
            v["rejection"] += "\n\nOA 글자 전체 (원문)\n" + oa
        out = call_with_one_retry(O.STEP, v, O.OpinionOut, ctx)
        for k in TITLES:
            if t := getattr(out, k):
                parts[k].append(t)
    return {t: "\n\n".join(parts[k][:1] if k == "closing" else parts[k]) for k, t in TITLES.items()}


def sub_main():
    """셋째 비교 (구독): ours와 OA 전체 글을 더한 ours_oa를 한 번씩. 폴더·회차 뒤에 OA 글자 파일을 준다."""
    import run as R

    from patent_ai.core.llm.transport import TransportError, TransportResponse

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

    assert not any(k.endswith("_API_KEY") for k in os.environ), (
        "키가 있으면 유료 호출이 나갈 수 있다"
    )
    inp = F4Input.model_validate_json((folder / "f4_input.json").read_text())
    plan = json.loads((folder / "plan.json").read_text())
    oa = json.loads(Path(sys.argv[3]).read_text())["oa"]
    # 판 이름에 든 낱말로 켠다: oa = OA 전체 글, before = 보정 전 글
    arms = sys.argv[4].split(",") if len(sys.argv) > 4 else ["ours_sub", "ours_oa_sub"]
    for name in arms:
        text = oa if "_oa" in name else None
        dest = folder / f"{name}_r{rep}.json"
        if not dest.exists():
            ctx = RunContext(
                f"{name}-{rep}", CallBudget(), MemoryRecorder(), transport=Sub(), cache=False
            )
            dest.write_text(
                json.dumps(
                    ours(inp, plan, ctx, text, "before" in name), ensure_ascii=False, indent=1
                )
            )
            print("DONE", folder.name, rep, name, "호출", len(ctx.recorder.records), flush=True)


def main():
    inp = F4Input.model_validate_json((folder / "f4_input.json").read_text())
    plan = json.loads((folder / "plan.json").read_text())
    ctx = RunContext(f"combine-{folder.name}-{rep}", CallBudget(), MemoryRecorder(), cache=False)
    path = folder / f"f4_r{rep}.json"
    if not path.exists():
        f4 = (
            (folder / "f4.json").read_text()
            if rep == 1
            else run_f4(inp, ctx=ctx, options=load_f4_options()).model_dump_json()
        )
        path.write_text(f4)
    dest = folder / f"ours_r{rep}.json"
    if not dest.exists():
        dest.write_text(json.dumps(ours(inp, plan, ctx), ensure_ascii=False, indent=1))
    r = ctx.recorder.records
    print(
        "DONE",
        folder.name,
        rep,
        "호출",
        len(r),
        "in",
        sum(x.input_tokens or 0 for x in r),
        "out",
        sum(x.output_tokens or 0 for x in r),
    )


sub_main() if len(sys.argv) > 3 else main()
