"""Compare the saved F4 decisions and amendment text to reviewed filing records."""

import argparse
import re
from collections import Counter
from hashlib import sha256
from pathlib import Path

from judge import read_json, write_json, write_rows
from sources import compact, pdf_pages

from eval.f4.gold import F4Gold
from eval.f4.pred import F4Pred
from eval.f4.score import predicted, score_oa
from patent_ai.core.f4_response_draft.result import F4Output

VARIANTS = ("current", "bm25", "verified_passages")
SPEC = re.compile(r"\[\d{4}\]")
CLAIM_ID = re.compile(r"(?:【보정대상항목】\s*|^)(?:청구항\s*)?(\d+)(?:항)?\s*$")


def filing_pages(folder, ref):
    (path,) = folder.glob(f"*_{ref}.pdf")
    return {
        "path": str(path),
        "sha256": sha256(path.read_bytes()).hexdigest(),
        "pages": [dict(page=i, lines=lines) for i, lines in enumerate(pdf_pages(path), 1)],
    }


def operations(text):
    changes = {}
    number = None
    for page in text["pages"]:
        for i, raw in enumerate(page["lines"], 1):
            line = raw.strip()
            if "【보정대상항목】" in line:
                match = CLAIM_ID.fullmatch(line)
                number = int(match[1]) if match else None
                if number is not None:
                    changes[number] = {"page": page["page"], "line": i, "lines": [line]}
            elif number is not None:
                changes[number]["lines"].append(line)
    return changes


def draft_operations(result):
    if not result.drafts:
        return {}
    return {claim.claim: claim for claim in result.drafts.claims}


def compare(repo, baseline, run):
    out = []
    fingerprints = {}
    for case in read_json(baseline / "manifest.json")["cases"]:
        alias = case["case"]
        goldpath = repo / case["response_direction_gold"]
        gold = F4Gold.model_validate_json(goldpath.read_text())
        goldraw = read_json(goldpath)
        app = (repo / case["oa_pdf"]).parent.parent.name
        folder = repo / "data/goldsets/tune/case_full" / app
        opinion = filing_pages(folder, goldraw["source"]["opinion"])
        amendment = filing_pages(folder, goldraw["source"]["amendment"])
        write_json(
            run / "filed-source-local" / f"{alias}.json",
            {
                "opinion": opinion,
                "amendment": amendment,
                "direction_gold": goldraw,
            },
        )
        fingerprints[alias] = {
            "direction_gold": sha256(goldpath.read_bytes()).hexdigest(),
            "opinion_pdf": opinion["sha256"],
            "amendment_pdf": amendment["sha256"],
        }
        actual_operations = operations(amendment)
        for variant in VARIANTS:
            path = baseline / "draft-comparison" / alias / variant / "result.json"
            result = F4Output.model_validate_json(path.read_text())
            dirs = {d.unit_id: d for d in result.directions}
            pred = F4Pred(result.units, dirs)
            amendments = draft_operations(result)
            review_rows = []
            for row in gold.claim_rows:
                reading = predicted(pred, row)
                claim = amendments.get(row.claim)
                relevant = [
                    unit
                    for unit in result.units
                    if unit.rejection == row.rejection
                    and row.claim in unit.claims
                    and unit.unit_id in dirs
                ]
                smallest = min((len(unit.claims) for unit in relevant), default=0)
                predictions = []
                for unit in relevant:
                    if len(unit.claims) != smallest:
                        continue
                    candidate_list = dirs[unit.unit_id].candidates
                    best = next((c for c in candidate_list if c.rank == 1), None)
                    best = best or (candidate_list[0] if candidate_list else None)
                    if best is None:
                        continue
                    edit = next((a for a in best.amendment_core if a.claim == row.claim), None)
                    predictions.append(
                        {
                            "unit_id": unit.unit_id,
                            "candidate_id": best.candidate_id,
                            "rank": best.rank,
                            "kind": edit.kind.value if edit else "unchanged",
                            "source_kind": edit.source.value if edit and edit.source else None,
                            "held": unit.unit_id in result.held_units,
                        }
                    )
                gold_kinds = set(row.amend_kinds)
                kind_set = {"none" if p["kind"] == "unchanged" else p["kind"] for p in predictions}
                text_state = "absent"
                if claim is not None:
                    if not claim.ai_text:
                        text_state = "held"
                    elif re.fullmatch(r"\(?\s*삭제\s*\)?", claim.ai_text.strip()):
                        text_state = "deleted"
                    elif compact(claim.ai_text) == compact(claim.before or ""):
                        text_state = "unchanged"
                    else:
                        text_state = "changed"
                if text_state == "deleted":
                    draft_kinds = {"delete"}
                elif text_state in {"absent", "unchanged"} and kind_set <= {"none"}:
                    draft_kinds = {"none"}
                elif text_state == "changed" and len(kind_set) == 1 and "none" not in kind_set:
                    draft_kinds = kind_set
                else:
                    draft_kinds = set()
                # A direction candidate may have a single kind while the gold can carry multiple.
                kind_match = (
                    "unassessable"
                    if not draft_kinds
                    else "exact"
                    if draft_kinds == gold_kinds
                    else "partial"
                    if draft_kinds & gold_kinds
                    else "mismatch"
                )
                actual_spec = {
                    src.removeprefix("spec:") for src in row.added_from if src.startswith("spec:")
                }
                draft_spec = (
                    {
                        spec
                        for ref in claim.spec_basis
                        if ref.location
                        for spec in SPEC.findall(ref.location)
                    }
                    if claim is not None and text_state == "changed"
                    else set()
                )
                filed_change = actual_operations.get(row.claim)
                if not row.handled:
                    scope = "gold_not_handled"
                elif row.inherited:
                    scope = "gold_inherited"
                else:
                    scope = "primary"
                decision = reading.default if reading else "uncovered"
                review_rows.append(
                    {
                        "case": alias,
                        "variant": variant,
                        "rejection": row.rejection,
                        "claim": row.claim,
                        "scope": scope,
                        "gold_direction": row.direction,
                        "predicted_direction": decision,
                        "direction_match": decision == row.direction
                        if decision != "conflict"
                        else None,
                        "gold_amendment_kinds": sorted(gold_kinds),
                        "recorded_candidate_amendment_kinds": sorted(kind_set),
                        "draft_kinds_backed_by_output": sorted(draft_kinds),
                        "amendment_kind_match": kind_match,
                        "draft_text_state": text_state,
                        "draft_amendment_text": claim.ai_text if claim else None,
                        "filed_change_location": filed_change,
                        "gold_basis": list(row.added_from),
                        "gold_spec_labels": sorted(actual_spec),
                        "draft_spec_labels": sorted(draft_spec),
                        "basis_overlap": sorted(draft_spec & actual_spec),
                        "spec_match": (
                            "not_applicable"
                            if not actual_spec
                            else "exact"
                            if draft_spec == actual_spec
                            else "partial"
                            if draft_spec & actual_spec
                            else "none"
                        ),
                        "candidate_records": predictions,
                        "review_required": kind_match in ("partial", "unassessable")
                        or bool([x for x in row.added_from if x.startswith("claim:")]),
                    }
                )
            out.extend(review_rows)
            direct = [
                row["direction_match"]
                for row in review_rows
                if row["scope"] == "primary" and row["direction_match"] is not None
            ]
            assert direct == score_oa(gold, pred).direction
    write_rows(run / "filed-comparison.jsonl", out)
    write_json(run / "filed-fingerprints.json", fingerprints)
    counts = {}
    for variant in VARIANTS:
        rows = [row for row in out if row["variant"] == variant and row["scope"] == "primary"]
        directions = [row["direction_match"] for row in rows if row["direction_match"] is not None]
        spec = [row["spec_match"] for row in rows if row["spec_match"] != "not_applicable"]
        counts[variant] = {
            "gold_primary_rows": len(rows),
            "directions_match": sum(directions),
            "directions_scored": len(directions),
            "amendment_kinds": Counter(row["amendment_kind_match"] for row in rows),
            "spec_labels": Counter(spec),
            "spec_labels_scored": len(spec),
        }
    write_json(run / "filed-summary.json", counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    compare(args.repo, args.baseline, args.run)


if __name__ == "__main__":
    main()
