"""Validate, freeze and summarize judgements made in the current Codex session."""

import argparse
import csv
from collections import Counter
from hashlib import sha256
from pathlib import Path

from judge import read_json, write_json, write_rows
from sources import locator

RESPONSE_LABELS = {"direct", "partial", "omitted", "unassessable"}
SUPPORT_LABELS = {"supported", "partial", "unsupported", "contradicted", "unverifiable"}


def table(folder, name):
    with (folder / f"{name}.tsv").open(encoding="utf-8") as file:
        return list(csv.DictReader(file, delimiter="\t"))


def split(value):
    return value.split(",") if value else []


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def record_check(row, data, catalog, evidence_id, draft, variant):
    keys = split(row["evidence_source_ids"])
    known = {x["source_id"]: x for group in catalog.values() for x in group}
    assert set(keys) <= set(known), (draft, keys, set(keys) - set(known))
    assert row["anchor"] in data["opinion_lines"] and row["support"] in SUPPORT_LABELS
    loc, matched = locator(
        {
            "source": row["source"],
            "locations": split(row["locations"]),
            "quoted": row["quote"],
            "proposition": data["opinion_lines"][row["anchor"]],
        },
        catalog,
    )
    return {
        "evidence_id": evidence_id,
        "draft": draft,
        "variant": variant,
        "issue_id": f"{draft[:3]}-I{row['issue']}",
        "anchor": row["anchor"],
        "draft_sentence": data["opinion_lines"][row["anchor"]],
        "cited_source": row["source"],
        "cited_locations": split(row["locations"]),
        "quoted_in_draft": row["quote"] or None,
        "reference_position": row["position_override"]
        or ("accurate" if loc == "quote_unverified" else loc),
        "citation_position": row["position_override"] or loc,
        "locator_before_override": loc,
        "matched_locations": sorted({x["source_id"] for x in matched if x["match"] == "cited"}),
        "support": row["support"],
        "source_records": [known[key] for key in keys],
        "reason": row["reason"],
    }


def combine(root, run):
    local = run / "session-judge"
    drafts = {p.stem: read_json(p) for p in sorted((run / "response-input").glob("*.json"))}
    key = {
        f"{case['case']}-{alias[-1]}": condition
        for case in read_json(root / "condition-key-local.json")
        for alias, condition in case["draft_labels"].items()
    }
    catalogs = {
        case: read_json(run / "source-catalog-local" / f"{case}.json")["sources"]
        for case in sorted({name[:3] for name in drafts})
    }
    assert len(drafts) == 12 and set(drafts) == set(key)
    evidence = []
    indexed_evidence = {}
    for row in table(local, "evidence"):
        for draft in split(row["drafts"]):
            rec = record_check(
                row,
                drafts[draft],
                catalogs[draft[:3]],
                f"E{len(evidence) + 1:03}",
                draft,
                key[draft],
            )
            evidence.append(rec)
            indexed_evidence.setdefault((draft, rec["issue_id"]), []).append(rec)

    reasons = {}
    for row in table(local, "responses"):
        for number in split(row["issues"]):
            token = row["draft"], f"{row['draft'][:3]}-I{number}"
            assert token not in reasons and row["response"] in RESPONSE_LABELS
            reasons[token] = row

    results = []
    for draft, data in drafts.items():
        anchors = {
            **data["opinion_lines"],
            **{x["anchor"]: x["draft_text"] or x["held_reason"] for x in data["amendments"]},
        }
        for issue in data["issues"]:
            token = draft, issue["issue_id"]
            row = reasons.pop(token)
            cites = indexed_evidence.pop(token, [])
            ids = split(row["anchors"])
            assert set(ids) <= set(anchors), (token, set(ids) - set(anchors))
            assert ids or row["response"] in {"omitted", "unassessable"}
            review = []
            if row["response"] != "direct":
                review.append(f"response_{row['response']}")
            if any(x["citation_position"] not in {"accurate", "no_citation"} for x in cites):
                review.append("citation_location")
            if any(x["support"] != "supported" for x in cites):
                review.append("assertion_support")
            if not cites and row["response"] in {"direct", "partial"}:
                review.append("evidence_check_not_sampled")
            if issue["scope"] == "out_of_product_scope":
                review.append("product_scope")
            results.append(
                {
                    **issue,
                    "draft": draft,
                    "variant": key[draft],
                    "response": row["response"],
                    "draft_locations": [{"anchor": i, "text": anchors[i]} for i in ids],
                    "reason": row["reason"],
                    "citation_check_ids": [x["evidence_id"] for x in cites],
                    "citation_position_counts": Counter(x["citation_position"] for x in cites),
                    "support_counts": Counter(x["support"] for x in cites),
                    "human_review_required": bool(review),
                    "review_reasons": review,
                }
            )
    assert not reasons and not indexed_evidence

    amend_reasons = {(r["draft"], r["anchor"]): r for r in table(local, "amendments")}
    found_support = {
        (draft, r["anchor"]): r
        for r in table(local, "amend-support")
        for draft in split(r["drafts"])
    }
    amendments = []
    for draft, data in drafts.items():
        for item in data["amendments"]:
            token = draft, item["anchor"]
            row = amend_reasons.pop(token)
            support = found_support.pop(token, {})
            if row["state"] == "changed":
                assert support["support"] in SUPPORT_LABELS
            basis = []
            catalog = catalogs[draft[:3]]
            known = {x["source_id"]: x for group in catalog.values() for x in group}
            for ref in item["basis"]:
                check = {
                    "source": "SPEC",
                    "locations": [ref["location"]] if ref["location"] else [],
                    "pages": [ref["page"]] if ref["page"] else [],
                    "quoted": ref["raw_text"],
                    "proposition": row["change"],
                }
                label, matches = locator(check, catalog)
                basis.append(
                    {
                        **ref,
                        "citation_position": label,
                        "sources": [x for x in matches if x["match"] == "cited"],
                    }
                )
            kinds = []
            if row["state"] == "held":
                kinds.append("held")
            if row["cross_document"] == "inconsistent":
                kinds.append("document_inconsistency")
            if support and support["support"] != "supported":
                kinds.append("amendment_support")
            if any(ref["citation_position"] != "accurate" for ref in basis):
                kinds.append("amendment_citation")
            amendments.append(
                {
                    **item,
                    **row,
                    "variant": key[draft],
                    "basis": basis,
                    "support": support.get("support", "not_applicable"),
                    "support_reason": support.get("reason"),
                    "source_records": [known[k] for k in split(support.get("evidence_source_ids"))],
                    "human_review_required": bool(kinds),
                    "review_reasons": kinds,
                }
            )
    assert not amend_reasons and not found_support
    return results, evidence, amendments


def aggregate(results, evidence, amendments):
    variants = sorted({r["variant"] for r in results})
    evidence_by_id = {row["evidence_id"]: row for row in evidence}
    summary = {}
    for variant in variants:
        in_scope = [r for r in results if r["variant"] == variant and r["scope"] == "supported"]
        checks = [evidence_by_id[k] for row in in_scope for k in row["citation_check_ids"]]
        changes = [r for r in amendments if r["variant"] == variant]
        summary[variant] = {
            "issue_rows": len(in_scope),
            "response_labels": Counter(r["response"] for r in in_scope),
            "issue_rows_with_sampled_claim_checks": sum(
                bool(r["citation_check_ids"]) for r in in_scope
            ),
            "sampled_claim_checks": len(checks),
            "reference_positions": Counter(c["reference_position"] for c in checks),
            "citation_positions": Counter(c["citation_position"] for c in checks),
            "support_labels": Counter(c["support"] for c in checks),
            "amendment_states": Counter(c["state"] for c in changes),
            "amendment_support": Counter(c["support"] for c in changes),
            "amendment_citation_positions": Counter(
                b["citation_position"] for c in changes for b in c["basis"]
            ),
            "cross_document": Counter(c["cross_document"] for c in changes),
        }
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    results, evidence, amendments = combine(args.root, args.run)
    write_rows(args.run / "results.jsonl", results)
    write_rows(args.run / "evidence-results.jsonl", evidence)
    write_rows(args.run / "amendment-results.jsonl", amendments)
    write_rows(
        args.run / "human-review.jsonl",
        (
            {"review_type": kind, **row}
            for kind, rows in (("issue", results), ("amendment", amendments))
            for row in rows
            if row["human_review_required"]
        ),
    )
    write_json(args.run / "summary.json", aggregate(results, evidence, amendments))
    local = args.run / "session-judge"
    write_json(
        args.run / "judgement-freeze.json",
        {
            "execution": "current Codex session, 1 judgement pass, authored TSVs",
            "runtime": read_json(local / "runtime.json"),
            "condition_key_used_for": "aggregation after judgement tables were written",
            "blinding_limit": (
                "same session also worked on filing comparison "
                "and saw selected upstream direction metadata"
            ),
            "independent_api_calls_executed": 0,
            "independent_api_status": (
                "automatic approval review rejected transmitting case material"
            ),
            "judgement_tables_sha256": {
                path.name: digest(path) for path in sorted(local.glob("*.tsv"))
            },
            "response_input_sha256": {
                path.name: digest(path)
                for path in sorted((args.run / "response-input").glob("*.json"))
            },
        },
    )


if __name__ == "__main__":
    main()
