"""Verify actual requests and summarize paired coverage and amendment checks."""

import argparse
import re
from collections import Counter
from pathlib import Path

from spec_cap_evaluate import case_paragraphs, lines, read
from spec_cap_generate import digest, dump


def compare_requests(case_dir):
    by_arm = {}
    for cap in (5, 10):
        folder = case_dir / f"spec{cap}"
        passages = read(folder / "passages.json")
        first_calls = {}
        requests = lines(folder / "requests.jsonl")
        for row in requests:
            prompt = row["prompt"]
            assert digest(prompt) == row["prompt_sha256"]
            if row["step"] != "f4.direction" or row["attempt"] != 1:
                continue
            if row["unit"] in passages:
                frozen = passages[row["unit"]]
                assert row["passage_ids"] == frozen["chunk_ids"]
                assert prompt.count(frozen["spec_passages"]) == 1
                prompt = prompt.replace(frozen["spec_passages"], "<passage-treatment>", 1)
            if row["unit"] in first_calls:
                raise ValueError("Duplicate first direction request")
            first_calls[row["unit"]] = prompt
        by_arm[cap] = first_calls
    assert by_arm[5] == by_arm[10]
    return len(by_arm[5])


def candidate_use(pilot, case, case_dir):
    chunks = {row["chunk"]["chunk_id"]: row["chunk"] for row in case_paragraphs(pilot, case)}
    small = read(case_dir / "spec5/passages.json")
    large = read(case_dir / "spec10/passages.json")
    other = read(case_dir / "input.json")
    stored = read(case_dir / "spec10/result.json")["drafts"] or {}
    extra_sources = []
    for unit, entry in large.items():
        shared = set(small[unit]["chunk_ids"])
        for cid in entry["chunk_ids"]:
            if cid in shared:
                continue
            chunk = chunks[cid]
            label = chunk["location"]["label"]
            opinion_lines = [
                {"section": item["key"], "line": line}
                for item in stored.get("opinion", [])
                for line in item["ai_text"].splitlines()
                if re.fullmatch(r"\[\d{4}\]", label) and label in line
            ]
            amendment_uses = [
                item["claim"]
                for item in stored.get("claims", [])
                if item["unit_id"] == unit
                and any(
                    b["location"] == label and b["document_id"] == chunk["doc_id"]
                    for b in item["spec_basis"]
                )
            ]
            comparison_quote_context = [
                effect
                for table in other["tables"]
                if table["unit_id"] == unit
                for effect in table["summary"].get("effect_candidates", [])
                if label in effect
            ]
            extra_sources.append(
                {
                    "case": case,
                    "unit_id": unit,
                    "chunk_id": cid,
                    "location": label,
                    "opinion_location_mentions_any_unit": opinion_lines,
                    "amendment_claims_same_unit_and_source": amendment_uses,
                    "already_in_shared_comparison_effect_candidates": comparison_quote_context,
                }
            )
    return extra_sources


def grade_case(case_dir):
    loc = case_dir / "judge"
    mapping = read(loc / "arm-map-local.json")
    grades = {}
    for letter, cap in mapping.items():
        evaluation = read(loc / f"{letter}-evaluation.json")
        payload = read(loc / f"{letter}-payload.json")
        info = {item["row_id"]: item for item in payload["amendments"]}
        exact = evaluation["opinion_quote_exact"]
        unsupported = 0
        counts = Counter()
        for row in evaluation["coverage"]:
            if row["status"] != "omitted" and not exact[row["issue_id"]]:
                unsupported += 1
            counts[row["status"]] += 1
        amendments = []
        for grade in evaluation["amendments"]:
            entry = info[grade["row_id"]]
            amendments.append(
                {
                    "claim": entry["claim"],
                    "rejection": entry["rejection"],
                    "normalized_text_comparison": entry["normalized_text_comparison"],
                    "locations": [s["location"] for s in entry["sources"]],
                    "exact_source_quotes": sum(
                        any(
                            q["quote_verified_at_stated_page_and_location"]
                            for q in source["matched_original"]
                        )
                        for source in entry["sources"]
                    ),
                    "source_quotes": len(entry["sources"]),
                    **grade,
                }
            )
        grades[cap] = {
            "coverage": dict(counts),
            "coverage_without_verbatim_quote": unsupported,
            "issues": evaluation["coverage"],
            "amendments": amendments,
            "usage": read(case_dir / f"spec{cap}/summary.json"),
            "judge_usage": read(loc / f"{letter}-usage.json"),
        }
    return grades


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pilot", type=Path)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--case", action="append", choices=("C01", "C02", "C03", "C04"))
    args = parser.parse_args()
    folder = args.folder
    manifest = read(folder / "manifest.json")
    summaries, paths = {}, []
    for case in args.case or manifest["cases"]:
        case_dir = folder / case
        grades = grade_case(case_dir)
        paths.extend(candidate_use(args.pilot, case, case_dir))
        a, b = ({q["issue_id"]: q for q in grades[cap]["issues"]} for cap in (5, 10))
        assert a.keys() == b.keys()
        summaries[case] = {
            "matched_first_direction_requests": compare_requests(case_dir),
            "arms": grades,
            "changed_issues": [
                {"issue_id": key, "spec5": a[key], "spec10": b[key]}
                for key in a
                if a[key]["status"] != b[key]["status"]
            ],
        }
    dump(folder / "comparison.json", summaries)
    dump(folder / "additional-passage-use.json", paths)
    for cap in (5, 10):
        counts = Counter()
        for r in summaries.values():
            counts.update(r["arms"][cap]["coverage"])
        print(cap, counts)


if __name__ == "__main__":
    main()
