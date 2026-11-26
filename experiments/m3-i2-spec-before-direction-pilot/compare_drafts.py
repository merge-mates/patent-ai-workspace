"""Replay frozen baseline inputs with original-spec passages in the direction prompt."""

import argparse
import json
from collections import Counter
from functools import partial
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import yaml
from spec_retrieval import ELIGIBLE_REASONS, read_jsonl

from patent_ai.core.f4_response_draft import llm_call
from patent_ai.core.f4_response_draft.inputs import F4Input
from patent_ai.core.f4_response_draft.result import F4Output
from patent_ai.core.f4_response_draft.run import run_f4
from patent_ai.core.llm.cache import FileCache
from patent_ai.core.llm.config import REPO_ROOT
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext


def passages_by_unit(inp, folder):
    chunks = {row["chunk"]["chunk_id"]: row for row in read_jsonl(folder / "paragraphs.jsonl")}
    queries = {
        (row["rejection"], row["claim"]): row["hits"]
        for row in read_jsonl(folder / "queries.jsonl")
        if row["variant"] == "claim"
    }
    reference = {
        (row["rejection"], row["claim"]): set(row["gold_paragraphs"])
        for row in read_jsonl(folder / "score-rows.jsonl")
        if row["variant"] == "claim"
    }
    output = {"bm25": {}, "verified_passages": {}}
    for unit in inp.units:
        if unit.rejection_kind.value not in ELIGIBLE_REASONS:
            continue
        pairs = [(unit.rejection, claim) for claim in unit.claims]
        scores = {}
        for pair in pairs:
            for hit in queries.get(pair, []):
                scores[hit["id"]] = max(scores.get(hit["id"], 0.0), 1 / hit["rank"])
        labels = set().union(*(reference.get(pair, set()) for pair in pairs))
        ranked = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
        output["bm25"][unit.unit_id] = [chunks[chunk_id] for chunk_id in ranked[:5]]
        output["verified_passages"][unit.unit_id] = [
            row for row in chunks.values() if row["chunk"]["location"]["label"] in labels
        ]
    return output


def write_draft(result, output):
    output.mkdir(parents=True, exist_ok=True)
    (output / "result.json").write_text(result.model_dump_json(indent=2) + "\n")
    draft = result.drafts
    if draft is None:
        (output / "draft.md").write_text("# 초안 보류\n\n실행 결과 JSON에 보류 상태가 있습니다.\n")
        return
    blocks = ["# 의견서 초안"]
    for section in draft.opinion:
        blocks.extend((f"## {section.title}", section.ai_text))
    blocks.append("# 보정안")
    for claim in draft.claims:
        blocks.extend((f"## 청구항 {claim.claim}", claim.ai_text or f"보류 — {claim.held_reason}"))
    (output / "draft.md").write_text("\n\n".join(blocks) + "\n")


def direction_metrics(gold_path, result):
    from eval.f4.gold import F4Gold
    from eval.f4.pred import F4Pred
    from eval.f4.score import score_oa

    gold = F4Gold.model_validate_json(gold_path.read_text())
    predictions = F4Pred(result.units, {row.unit_id: row for row in result.directions})
    direction = score_oa(gold, predictions).direction
    return {
        "direction_matches": sum(direction),
        "scored_rows": len(direction),
        "held_units": len(result.held_units),
        "opinion_sections": len(result.drafts.opinion) if result.drafts else 0,
        "amended_claims_with_text": sum(bool(claim.ai_text) for claim in result.drafts.claims)
        if result.drafts
        else 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--case", choices=("C01", "C02", "C03", "C04"))
    parser.add_argument("--variant", choices=("bm25", "verified_passages"))
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    baseline = args.run_dir / "cli-baseline"
    out = args.output.resolve()
    if out == (args.run_dir / "draft-comparison").resolve():
        parser.error("비교 결과는 기준선의 초안 폴더와 다른 위치에 기록해야 합니다")
    out.mkdir(parents=True, exist_ok=True)
    run_key = "-".join(value for value in (args.case, args.variant) if value)
    summary_path = out / (f"summary-{run_key}.json" if run_key else "summary.json")
    config_dir = out / "model-config" / (run_key or "all")
    config_dir.mkdir(parents=True, exist_ok=True)
    prompt = (REPO_ROOT / "prompts/f4/direction.md").read_text()
    note = Path(__file__).with_name("direction-spec-note.txt").read_text()
    prompt_path = config_dir / "direction-with-spec.md"
    prompt_path.write_text(prompt.replace("$retry_note", f"\n{note}\n$retry_note"))
    config = yaml.safe_load((REPO_ROOT / "config/f4.yaml").read_text())
    config["direction"]["prompt"] = str(prompt_path)
    (config_dir / "f4.yaml").write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
    normal_call = llm_call.call_model
    with_spec = partial(normal_call, config_dir=config_dir)
    info = []
    for case in json.loads((args.run_dir / "manifest.json").read_text())["cases"]:
        case_name = case["case"]
        if args.case and case_name != args.case:
            continue
        key = f"{Path(case['oa_pdf']).parent.parent.name}_{case['dispatch_number']}"
        gold_path = args.gold / f"{key}.json"
        try:
            input_path = args.run_dir / "draft-comparison" / case_name / "common-input.json"
            inp = F4Input.model_validate_json(input_path.read_text())
            control = F4Output.model_validate_json((baseline / f"f4/{key}.json").read_text())
        except FileNotFoundError as error:
            info.append(
                {"case": case_name, "status": "baseline_incomplete", "missing": str(error.filename)}
            )
            continue
        cases = passages_by_unit(inp, args.run_dir / "spec-retrieval" / case_name)
        write_draft(control, out / case_name / "current")
        input_hash = sha256(inp.model_dump_json().encode()).hexdigest()
        (out / case_name / "common-input.json").write_text(inp.model_dump_json(indent=2) + "\n")
        info.append(
            {
                "case": case_name,
                "variant": "current",
                "status": "complete" if control.drafts else "held",
                "common_input_sha256": input_hash,
                **direction_metrics(gold_path, control),
            }
        )
        for variant, passages in cases.items():
            if args.variant and variant != args.variant:
                continue
            target = out / case_name / variant
            target.mkdir(parents=True, exist_ok=True)
            (target / "passages.json").write_text(
                json.dumps(passages, ensure_ascii=False, indent=2)
            )
            if args.prepare_only:
                info.append({"case": case_name, "variant": variant, "status": "prepared"})
                continue
            ctx = RunContext(
                f"{case_name}-{variant}",
                CallBudget(),
                MemoryRecorder(),
                cache=FileCache(out / "model-cache"),
            )

            def call(step, variables, *args, active_passages=passages, **kwargs):
                if step != "f4.direction":
                    return normal_call(step, variables, *args, **kwargs)
                unit_id = json.loads(variables["unit"])["unit_id"]
                rows = active_passages.get(unit_id, [])
                if not rows:
                    return normal_call(step, variables, *args, **kwargs)
                text = "\n\n".join(
                    f"{r['chunk']['location']['label']} ({r['page']}쪽)\n{r['chunk']['text']}"
                    for r in rows
                )
                return with_spec(step, {**variables, "spec_passages": text}, *args, **kwargs)

            try:
                with patch.object(llm_call, "call_model", call):
                    result = run_f4(inp, ctx=ctx)
                write_draft(result, target)
                status = "complete" if result.drafts else "held"
                metrics = direction_metrics(gold_path, result)
            except Exception as error:
                status = type(error).__name__
                metrics = {}
            row = {
                "case": case_name,
                "variant": variant,
                "status": status,
                "common_input_sha256": input_hash,
                "units_with_passages": sum(map(bool, passages.values())),
                "calls_by_step": Counter(r.step for r in ctx.recorder.records if not r.from_cache),
                "input_tokens": sum(r.input_tokens for r in ctx.recorder.records),
                "output_tokens": sum(r.output_tokens for r in ctx.recorder.records),
                **metrics,
            }
            info.append(row)
            print(json.dumps({k: row[k] for k in ("case", "variant", "status")}), flush=True)
            summary_path.write_text(json.dumps(info, indent=2) + "\n")
    summary_path.write_text(json.dumps(info, indent=2) + "\n")
    return int(any(row["status"] not in {"complete", "held", "prepared"} for row in info))


if __name__ == "__main__":
    raise SystemExit(main())
