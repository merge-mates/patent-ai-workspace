"""Join OA issues to frozen retrieval, comparison, direction and draft anchors."""

import argparse
import csv
from hashlib import sha256
from pathlib import Path

from judge import read_json, read_rows, write_json, write_rows


def join(root, run, baseline, repo):
    cases = read_json(baseline / "manifest.json")["cases"]
    results = {(r["issue_id"], r["variant"]): r for r in read_rows(run / "results.jsonl")}
    by_claim = {
        (r["case"], r["variant"], r["rejection"], r["claim"]): r
        for r in read_rows(run / "filed-comparison.jsonl")
    }
    trace_rows = []
    query_rows = {}
    ft = run / "session-judge/trace-selection.tsv"
    with ft.open(encoding="utf-8") as file:
        for sel in csv.DictReader(file, delimiter="\t"):
            issue = results[sel["issue_id"], sel["condition"]]
            case, condition = issue["case"], issue["variant"]
            claim, rejection = int(sel["claim"]), issue["rejection"]
            tag = f"{case}-R{rejection}-C{claim}"
            retrieval = baseline / "spec-retrieval" / case
            (query,) = [
                r
                for r in read_rows(retrieval / "queries.jsonl")
                if r["claim"] == claim and r["rejection"] == rejection and r["variant"] == "claim"
            ]
            (gold,) = [
                r
                for r in read_rows(retrieval / "score-rows.jsonl")
                if r["claim"] == claim and r["rejection"] == rejection and r["variant"] == "claim"
            ]
            query_rows[tag] = {
                "query_id": tag,
                "case": case,
                **query,
                "expected": gold["gold_paragraphs"],
            }
            folder = baseline / "draft-comparison" / case
            result = read_json(folder / condition / "result.json")
            unit = min(
                (
                    u
                    for u in result["units"]
                    if claim in u["claims"] and u["rejection"] == rejection
                ),
                key=lambda unit: len(unit["claims"]),
            )
            (direction,) = [d for d in result["directions"] if d["unit_id"] == unit["unit_id"]]
            candidates = direction["candidates"]
            chosen = next((x for x in candidates if x["rank"] == 1), None)
            chosen = chosen or (candidates[0] if candidates else None)
            source = read_json(folder / "common-input.json")
            tables = [t for t in source["tables"] if t["unit_id"] == unit["unit_id"]]
            elements = [f"구성 {x}]" for x in sel["comparison_element"].split(",")]
            decisions = [
                {
                    key: row[key]
                    for key in (
                        "element_location",
                        "element",
                        "citation",
                        "judgment",
                        "evidence",
                        "why_retrieved",
                        "status",
                    )
                }
                for table in tables
                for row in table["rows"]
                if any(element in row["element_location"] for element in elements)
            ]
            passage_file = folder / condition / "passages.json"
            passages = (
                read_json(passage_file).get(unit["unit_id"], []) if passage_file.exists() else []
            )
            draft = read_json(run / "response-input" / f"{issue['draft']}.json")
            draft_lines = draft["opinion_lines"] | {
                a["anchor"]: a["draft_text"] for a in draft["amendments"]
            }
            filed = by_claim[case, condition, rejection, claim]
            trace_rows.append(
                {
                    "trace_id": f"{sel['issue_id']}-{condition}",
                    "case": case,
                    "draft": issue["draft"],
                    "condition": condition,
                    "issue_id": sel["issue_id"],
                    "examiner_proposition": issue["examiner_proposition"],
                    "oa_locations": issue["oa_locations"],
                    "query_id": tag,
                    "unit_id": unit["unit_id"],
                    "retrieval_hits": query["hits"],
                    "gold_paragraphs": gold["gold_paragraphs"],
                    "direction_input_passages": passages,
                    "frozen_prior_art_comparisons": decisions,
                    "direction_candidate": chosen,
                    "draft_locations": [
                        {"anchor": key, "text": draft_lines[key]}
                        for key in sel["anchors"].split(",")
                    ],
                    "judge_response": issue["response"],
                    "filed_change_location": filed["filed_change_location"],
                    "filed_basis_overlap": filed["basis_overlap"],
                    "observation": sel["observation"],
                    "failure_classes": sel["failure_classes"].split(","),
                    "human_review_required": True,
                }
            )
    write_rows(run / "queries.jsonl", query_rows.values())
    write_rows(run / "traces.jsonl", trace_rows)

    def digest(path):
        return sha256(path.read_bytes()).hexdigest()

    artifacts = {}
    for row in cases:
        case = row["case"]
        folder = baseline / "draft-comparison" / case
        sources = read_json(run / "source-catalog-local" / f"{case}.json")["files"]
        artifacts[case] = {
            "source_pdfs": sources,
            "stored_comparison_input_sha256": digest(folder / "common-input.json"),
            "frozen_drafts_sha256": {
                condition: digest(folder / condition / "result.json")
                for condition in ("current", "bm25", "verified_passages")
            },
            "retrieval_queries_sha256": digest(
                baseline / "spec-retrieval" / case / "queries.jsonl"
            ),
        }
    write_json(
        run / "manifest.json",
        {
            "date": "2026-11-24",
            "branch": "codex/oa-draft-judge",
            "starting_commit": "436aa75",
            "origin_experiment_commit": "96887ae",
            "coordination_sha256": digest(baseline / "coordination.md"),
            "issue_freeze": read_json(root / "01-source-freeze/freeze.json"),
            "ci_cli_settings": read_json(baseline / "cli-run-settings.json"),
            "index_fingerprints": {
                name: read_json(repo / "data/index" / f"{name}.fingerprint.json")
                for name in ("cite-idx-v5", "law-idx-v3")
            },
            "original_spec_index": "cite-spec-memory",
            "submitted_gold_version": 2,
            "submitted_fingerprints": read_json(run / "filed-fingerprints.json"),
            "draft_cases": artifacts,
            "execution": read_json(run / "judgement-freeze.json"),
            "output_sha256": {path.name: digest(path) for path in sorted(run.glob("*.jsonl"))},
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("run", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("repo", type=Path)
    args = parser.parse_args()
    join(args.root, args.run, args.baseline, args.repo)


if __name__ == "__main__":
    main()
