"""Recreate the originally reviewed issue freeze directly from hashed OA PDFs."""

import argparse
import csv
import json
from collections import Counter
from hashlib import sha256
from pathlib import Path

from judge import read_json, write_json, write_rows
from sources import pdf_pages


def freeze(repo, baseline, target):
    raw = read_json(baseline / "manifest.json")
    pages_by_case = {}
    for case in raw["cases"]:
        alias = case["case"]
        pdf = repo / case["oa_pdf"]
        if sha256(pdf.read_bytes()).hexdigest() != case["oa_pdf_sha256"]:
            raise ValueError(f"{alias}: OA PDF changed")
        pages = [
            {"page": i, "lines": [line.strip() for line in lines if line.strip()]}
            for i, lines in enumerate(pdf_pages(pdf), 1)
        ]
        pages_by_case[alias] = pages
        write_json(target / f"{alias}-pages.json", pages)
    cases = Counter()
    results = []
    with (target / "issue-decisions.tsv").open(encoding="utf-8") as file:
        for row in csv.DictReader(file, delimiter="\t"):
            case = row["case"]
            cases[case] += 1
            spans = []
            for loc in row.pop("locations").split(","):
                page_text, bounds = loc.split(":")
                page = int(page_text)
                first, last = map(int, bounds.split("-"))
                lines = pages_by_case[case][page - 1]["lines"][first - 1 : last]
                if len(lines) != last - first + 1:
                    raise ValueError(f"{case}: invalid source span {loc}")
                spans.append(
                    {
                        "page": page,
                        "start_line": first,
                        "end_line": last,
                        "quote": "\n".join(lines),
                    }
                )
            results.append(
                {
                    **row,
                    "issue_id": f"{case}-I{cases[case]:02}",
                    "rejection": int(row["rejection"]),
                    "claims": list(map(int, row["claims"].split(","))),
                    "oa_locations": spans,
                }
            )
    path = target / "issues.jsonl"
    regenerated = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in results).encode()
    if path.exists() and path.read_bytes() != regenerated:
        raise ValueError("Rebuilt OA issues differ from the original freeze")
    write_rows(path, results)
    write_json(
        target / "freeze.json",
        {
            "phase": "OA PDF only, frozen before the first draft body was opened",
            "issues_sha256": sha256(path.read_bytes()).hexdigest(),
            "counts_by_case": dict(cases),
            "counts_by_scope": dict(Counter(r["scope"] for r in results)),
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    freeze(args.repo, args.baseline, args.target)


if __name__ == "__main__":
    main()
