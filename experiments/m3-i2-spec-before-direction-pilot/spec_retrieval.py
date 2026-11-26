"""Four-case local BM25 pilot. Gold is opened after query generation and ranking."""

import argparse
import json
import re
from hashlib import sha256
from pathlib import Path
from statistics import mean

from patent_ai.core.f3_claim_compare.clarity import SpecChunk, _spec_searcher, split_spec
from patent_ai.core.f3_claim_compare.config import load_f3_settings
from patent_ai.core.f4_response_draft.inputs import F4Input
from patent_ai.core.schemas.oa_result import OAResult
from patent_ai.retrieval.schemas import Chunk

TOP_K = (1, 3, 5, 10)
GOLD_SPEC = re.compile(r"(?:명세서|spec):\s*\[(\d+)\]")
QUERY_VARIANTS = ("claim", "claim_and_oa")
ELIGIBLE_REASONS = {"novelty", "inventive_step"}


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def rank(case, run_dir, output, settings):
    oa_pdf = Path(case["oa_pdf"])
    application, dispatch = oa_pdf.parent.parent.name, case["dispatch_number"]
    name = f"{application}_{dispatch}"
    input_path = run_dir / "draft-comparison" / case["case"] / "common-input.json"
    inputs = F4Input.model_validate_json(input_path.read_text())
    claims = {claim.claim: claim.text for claim in inputs.claims_text}
    if inputs.spec is None or not claims:
        raise ValueError(f"{case['case']}: 청구항 또는 출원서 입력 누락")

    chunk_path = output / "paragraphs.jsonl"
    chunks = split_spec(inputs.spec, settings.clarity_search.skip_headings)
    if not chunks:
        raise ValueError(f"{case['case']}: 명세서 문단 0개")
    write_jsonl(
        chunk_path,
        [
            {"page": item.page, "chunk": item.chunk.model_dump(mode="json", exclude_none=True)}
            for item in chunks
        ],
    )
    chunks = [
        SpecChunk(Chunk.model_validate(row["chunk"]), row["page"]) for row in read_jsonl(chunk_path)
    ]
    searcher = _spec_searcher(chunks, settings)
    by_id = {item.chunk.chunk_id: item.page for item in chunks}
    queries = []
    for rejection in inputs.oa.rejections:
        if rejection.kind.value not in ELIGIBLE_REASONS:
            continue
        for claim in sorted(set(rejection.claims.value or [])):
            claim_text = " ".join(claims.get(claim, "").split())
            if not claim_text:
                continue
            reasoning = rejection.examiner_reasoning
            query_texts = (
                claim_text,
                f"{claim_text} {reasoning.value or reasoning.raw_text or ''}".strip(),
            )
            for variant, query in zip(QUERY_VARIANTS, query_texts, strict=True):
                retrieved = searcher.search(
                    query, "cite", "bm25", max(TOP_K), doc_ids=[inputs.spec.document_id]
                )
                queries.append(
                    {
                        "variant": variant,
                        "rejection": rejection.no,
                        "claim": claim,
                        "query": query,
                        "hits": [
                            {
                                "rank": hit.rank,
                                "id": hit.chunk_id,
                                "page": by_id[hit.chunk_id],
                                "location": hit.location.label,
                                "score": hit.score,
                            }
                            for hit in retrieved.hits
                        ],
                    }
                )
    write_jsonl(output / "queries.jsonl", queries)
    metadata = {
        "case": case["case"],
        "dispatch_number": dispatch,
        "page_count": len(inputs.spec.pages),
        "chunk_count": len(chunks),
        "query_count_per_variant": len(queries) // len(QUERY_VARIANTS),
        "frozen_input": str(input_path),
        "paragraphs_sha256": sha256(chunk_path.read_bytes()).hexdigest(),
    }
    return name, metadata, inputs.oa


def measure(name, metadata, oa: OAResult, output, gold_dir):
    gold_path = gold_dir / f"{name}.json"
    gold = json.loads(gold_path.read_text())["claim_rows"]
    available = {
        row["chunk"]["location"]["label"] for row in read_jsonl(output / "paragraphs.jsonl")
    }
    queries = {
        (row["variant"], row["rejection"], row["claim"]): row
        for row in read_jsonl(output / "queries.jsonl")
    }
    reason_kinds = {row.no: row.kind.value for row in oa.rejections}
    scored = []
    excluded = []
    for row in gold:
        expected = {
            f"[{int(m[1]):04d}]"
            for source in row["added_from"]
            if (m := GOLD_SPEC.fullmatch(source))
        }
        if not expected:
            continue
        pair = {
            "rejection": row["rejection"],
            "claim": row["claim"],
            "gold_paragraphs": sorted(expected),
            "unextracted_gold_paragraphs": sorted(expected - available),
        }
        kind = reason_kinds.get(row["rejection"])
        if kind is None:
            raise ValueError(
                f"{name}: gold rejection {row['rejection']} is missing from OA extraction"
            )
        if kind not in ELIGIBLE_REASONS:
            excluded.append({**pair, "reason": kind})
            continue
        for variant in QUERY_VARIANTS:
            query = queries.get((variant, row["rejection"], row["claim"]))
            hits = query["hits"] if query else []
            item = {**pair, "variant": variant, "has_query": query is not None}
            for k in TOP_K:
                matches = [hit for hit in hits[:k] if hit["location"] in expected]
                item[f"recall@{k}"] = len({hit["location"] for hit in matches}) / len(expected)
                item[f"mrr@{k}"] = 1 / matches[0]["rank"] if matches else 0.0
            scored.append(item)
    write_jsonl(output / "score-rows.jsonl", scored)
    write_jsonl(output / "excluded-rows.jsonl", excluded)
    variants = {
        variant: [row for row in scored if row["variant"] == variant] for variant in QUERY_VARIANTS
    }
    return {
        **metadata,
        "gold_rows": len(scored) // len(QUERY_VARIANTS),
        "excluded_gold_rows": len(excluded),
        "gold_rows_without_query": sum(not row["has_query"] for row in variants[QUERY_VARIANTS[0]]),
        "gold_paragraphs_missing_from_extraction": sorted(
            {value for row in scored + excluded for value in row["unextracted_gold_paragraphs"]}
        ),
        "variants": {
            variant: {
                metric: mean(row[metric] for row in rows) if rows else None
                for k in TOP_K
                for metric in (f"recall@{k}", f"mrr@{k}")
            }
            for variant, rows in variants.items()
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--detail-gold", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((args.run_dir / "manifest.json").read_text())
    settings = load_f3_settings()
    cases = []
    for case in manifest["cases"]:
        output = args.output / case["case"]
        output.mkdir(parents=True, exist_ok=True)
        name, metadata, oa = rank(case, args.run_dir, output, settings)
        cases.append((name, metadata, oa, output))
    summary = [measure(*case, args.detail_gold) for case in cases]
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
