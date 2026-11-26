"""Regenerate full OA responses from identical evidence with a 5/10 passage cap."""

import argparse
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import yaml
from compare_drafts import write_draft
from dotenv import load_dotenv

from patent_ai.core.f4_response_draft import llm_call
from patent_ai.core.f4_response_draft.inputs import F4Input
from patent_ai.core.f4_response_draft.run import run_f4
from patent_ai.core.llm.config import REPO_ROOT, load_step_config
from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext
from patent_ai.core.llm.prompts import render_prompt
from patent_ai.core.llm.transport import AnthropicTransport

HERE = Path(__file__).resolve().parent
CASE_ORDER = {"C01": (5, 10), "C02": (10, 5), "C03": (5, 10), "C04": (10, 5)}


def dump(path, value):
    part = path.with_suffix(path.suffix + ".tmp")
    part.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    part.replace(path)


def digest(text):
    return sha256(text.encode()).hexdigest()


def prepare(pilot, folder):
    source_passages = pilot / "round1-spec-propagation/direction-payloads.jsonl"
    config = folder / "config"
    config.mkdir(exist_ok=True, parents=True)
    original = (REPO_ROOT / "prompts/f4/direction.md").read_text()
    appendix = (HERE / "direction-spec-note.txt").read_text()
    path = config / "direction.md"
    path.write_text(original.replace("$retry_note", f"\n{appendix}\n$retry_note"))
    settings = yaml.safe_load((REPO_ROOT / "config/f4.yaml").read_text())
    settings["direction"]["prompt"] = str(path)
    (config / "f4.yaml").write_text(yaml.safe_dump(settings, allow_unicode=True, sort_keys=False))

    data = [json.loads(line) for line in source_passages.read_text().splitlines()]
    manifest = {
        "provider": "anthropic",
        "sources": {"passage_sha256": digest(source_passages.read_text())},
        "cases": {},
    }
    for case, order in CASE_ORDER.items():
        case_dir = folder / case
        case_dir.mkdir(exist_ok=True)
        source = pilot / "draft-comparison" / case / "common-input.json"
        raw = source.read_text()
        common = F4Input.model_validate_json(raw)
        chosen = {
            cap: {
                row["unit_id"]: row
                for row in data
                if row["case"] == case and row["policy"] == f"max_rank_{cap}"
            }
            for cap in order
        }
        units = {
            unit.unit_id
            for unit in common.units
            if unit.rejection_kind.value in {"novelty", "inventive_step"}
        }
        assert set(chosen[5]) == set(chosen[10]) == units
        for unit_id in units:
            small, large = chosen[5][unit_id], chosen[10][unit_id]
            assert small["chunk_ids"] == large["chunk_ids"][:5]
            assert len(large["chunk_ids"]) == 10
        (case_dir / "input.json").write_text(raw)
        for cap in order:
            arm = case_dir / f"spec{cap}"
            arm.mkdir(exist_ok=True)
            dump(arm / "passages.json", chosen[cap])
        manifest["cases"][case] = {
            "common_input_sha256": digest(raw),
            "order": order,
            "judgment_units": len(common.units),
            "units_with_passage_treatment": len(units),
        }
    manifest["models"] = {}
    for stage in ("direction", "opinion", "amendment"):
        opts = load_step_config(f"f4.{stage}")
        assert (opts.model, opts.effort) == ("claude-haiku-5-5", "medium")
        manifest["models"][stage] = {"model": opts.model, "effort": opts.effort}
        manifest["sources"][stage] = digest((REPO_ROOT / opts.prompt).read_text())
    manifest["sources"]["direction_treatment_template"] = digest(path.read_text())
    dump(folder / "manifest.json", manifest)
    return manifest


def run_case(folder, case):
    case_dir = folder / case
    common = F4Input.model_validate_json((case_dir / "input.json").read_text())
    for cap in CASE_ORDER[case]:
        target = case_dir / f"spec{cap}"
        if (target / "summary.json").exists():
            continue
        passages = json.loads((target / "passages.json").read_text())
        base = llm_call.call_model
        captured = target / "requests.jsonl"
        ctx = RunContext(
            f"{case}-spec{cap}", CallBudget(), MemoryRecorder(), AnthropicTransport(), False
        )

        def model_call(
            step, values, *args, passages=passages, captured=captured, base=base, **kwargs
        ):
            unit_raw = values.get("unit")
            unit = json.loads(unit_raw)["unit_id"] if unit_raw else None
            treatment = step == "f4.direction" and unit in passages
            config_dir = folder / "config" if treatment else None
            variables = (
                {**values, "spec_passages": passages[unit]["spec_passages"]}
                if treatment
                else values
            )
            opts = load_step_config(step, config_dir)
            prompt = render_prompt(opts.prompt, variables, REPO_ROOT)
            with captured.open("a", encoding="utf-8") as output:
                output.write(
                    json.dumps(
                        {
                            "step": step,
                            "unit": unit,
                            "attempt": kwargs.get("attempt"),
                            "model": opts.model,
                            "effort": opts.effort,
                            "prompt_sha256": digest(prompt),
                            "prompt": prompt,
                            "passage_ids": passages[unit]["chunk_ids"] if treatment else [],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            return base(step, variables, *args, config_dir=config_dir, **kwargs)

        start = time.perf_counter()
        print(f"{case} spec{cap} started", flush=True)
        try:
            with patch.object(llm_call, "call_model", model_call):
                result = run_f4(common, ctx=ctx)
        finally:
            dump(target / "model-calls.json", [asdict(record) for record in ctx.recorder.records])
        write_draft(result, target)
        cost = {
            "elapsed_s": round(time.perf_counter() - start, 3),
            "calls_logged": len(ctx.recorder.records),
            "input_tokens": sum(record.input_tokens or 0 for record in ctx.recorder.records),
            "output_tokens": sum(record.output_tokens or 0 for record in ctx.recorder.records),
            "held_units": result.held_units,
            "draft_present": result.drafts is not None,
        }
        dump(target / "summary.json", cost)
        print(f"{case} spec{cap} finished {cost['calls_logged']} recorded calls", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pilot", type=Path)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--case", choices=tuple(CASE_ORDER), action="append")
    args = parser.parse_args()
    folder = args.folder.resolve()
    manifest = prepare(args.pilot.resolve(), folder)
    if not args.live:
        print(manifest["cases"])
        return
    load_dotenv(REPO_ROOT / ".env")
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is missing")
    os.environ["ANTHROPIC_BASE_URL"] = "https://api.anthropic.com"
    cases = args.case or tuple(CASE_ORDER)
    with ProcessPoolExecutor(max_workers=min(4, len(cases))) as pool:
        futures = [pool.submit(run_case, folder, case) for case in cases]
        for future in futures:
            future.result()


if __name__ == "__main__":
    main()
