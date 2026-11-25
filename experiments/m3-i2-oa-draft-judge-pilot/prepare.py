"""Freeze OA source records and condition-blinded drafts for issue-level review."""

import argparse
import json
from hashlib import sha256
from pathlib import Path

VARIANTS = ("current", "bm25", "verified_passages")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare_case(source, output, case):
    parent = source / "draft-comparison" / case
    frozen = load(parent / "common-input.json")
    oa = frozen["oa"]
    output.mkdir(parents=True, exist_ok=True)
    save(
        output / "oa-evidence.json",
        {
            "case": case,
            "oa": oa,
            "claims_at_oa": frozen["claims_text"],
            "specification": frozen["spec"],
            "resolved_comparison_evidence": frozen["tables"],
            "resolved_legal_evidence": frozen["legal"],
        },
    )
    checklist = [
        {
            "oa_rejection": r["no"],
            "kind": r["kind"],
            "supported": r["supported"],
            "claims": r["claims"],
            "reasoning": r["examiner_reasoning"],
        }
        for r in oa["rejections"]
    ]
    save(output / "issue-review-input.json", {"oa_rejections": checklist, "issues": []})

    blinded = []
    key = {}
    labels = ["초안 A", "초안 B", "초안 C"]
    ordered = sorted(VARIANTS, key=lambda mode: sha256(f"{case}:{mode}".encode()).hexdigest())
    for label, mode in zip(labels, ordered, strict=True):
        result = load(parent / mode / "result.json")
        draft = result["drafts"]
        key[label] = mode
        blinded.append(
            {
                "draft": label,
                "opinion": [{"section": s["title"], "text": s["ai_text"]} for s in draft["opinion"]]
                if draft
                else [],
                "amendments": [
                    {
                        "claim": c["claim"],
                        "original": c["before"],
                        "draft_text": c["ai_text"],
                        "basis": c["spec_basis"],
                        "held_reason": c["held_reason"],
                    }
                    for c in draft["claims"]
                ]
                if draft
                else [],
                "held_units": result["held_units"],
            }
        )
    save(output / "drafts-blinded.json", blinded)
    return {"case": case, "rejections_to_review": len(checklist), "draft_labels": key}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cases = load(args.source / "manifest.json")["cases"]
    records = [prepare_case(args.source, args.output / c["case"], c["case"]) for c in cases]
    save(args.output / "condition-key-local.json", records)
    lines = [
        "# 초안 채점 입력 준비",
        "",
        "네 사건을 동결했다. OA 거절이유 수는 검수 대상이며 "
        "개별 논점 분모는 아직 확정되지 않았다. 모델이나 사람이 초안을 채점할 때는 "
        "조건 키 파일을 판정 입력에 포함하지 않는다.",
        "",
        "| 사건 | OA 거절이유 | 가린 초안 |",
        "|---|---:|---:|",
    ]
    lines.extend(
        f"| [{r['case']}]({r['case']}/issue-review-input.json) | {r['rejections_to_review']} | 3 |"
        for r in records
    )
    (args.output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Prepared {len(records)} cases and {len(records) * len(VARIANTS)} drafts")


if __name__ == "__main__":
    main()
