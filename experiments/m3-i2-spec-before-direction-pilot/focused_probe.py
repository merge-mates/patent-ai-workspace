"""Offline paired BM25 probe using one focused query per frozen baseline row."""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

from spec_retrieval import read_jsonl, write_jsonl

from patent_ai.core.f3_claim_compare.clarity import SpecChunk, _spec_searcher
from patent_ai.core.f3_claim_compare.config import load_f3_settings
from patent_ai.retrieval.schemas import Chunk


def difference_terms(rows, claim):
    outcomes = defaultdict(set)
    for row in rows:
        if row["claim"] != claim:
            continue
        text = " ".join(row["element"].split())
        if text and text not in {"확인되지 않음", "확인 안 됨"}:
            outcomes[text].add(row["judgment"])
    return [
        text
        for text, values in outcomes.items()
        if "difference_candidate" in values and "disclosed" not in values
    ]


def choose_query(inp, rejection, claim, whole_claim):
    units = {
        unit["unit_id"]: unit
        for unit in inp["units"]
        if unit["rejection"] == rejection and claim in unit["claims"]
    }
    tables = [table for table in inp["tables"] if table["unit_id"] in units]
    direct = [text for table in tables for text in difference_terms(table["rows"], claim)]
    if direct:
        return " ".join(dict.fromkeys(direct)), "청구항 자체 차이 후보"
    representatives = [
        text
        for table in tables
        for text in difference_terms(table["rows"], units[table["unit_id"]]["representative_claim"])
    ]
    if representatives:
        return " ".join(dict.fromkeys(representatives)), "대표 청구항 차이 후보"
    return whole_claim, "차이 후보 미확인 · 전체 청구항 사용"


def metrics(labels, hits, k):
    matches = [(i, hit) for i, hit in enumerate(hits[:k], start=1) if hit in labels]
    return len({hit for _, hit in matches}) / len(labels), 1 / matches[0][0] if matches else 0


def run_case(source, case, output, settings):
    old = source / "spec-retrieval" / case
    content = read_jsonl(old / "paragraphs.jsonl")
    chunks = [SpecChunk(Chunk.model_validate(r["chunk"]), r["page"]) for r in content]
    searcher = _spec_searcher(chunks, settings)
    inp = json.loads((source / "draft-comparison" / case / "common-input.json").read_text())
    before = [row for row in read_jsonl(old / "queries.jsonl") if row["variant"] == "claim"]
    rows = []
    for baseline in before:
        rejection, claim = baseline["rejection"], baseline["claim"]
        query, basis = choose_query(inp, rejection, claim, baseline["query"])
        search = searcher.search(query, "cite", "bm25", 10, doc_ids=[chunks[0].chunk.doc_id])
        rows.append(
            {
                "rejection": rejection,
                "claim": claim,
                "baseline_query": baseline["query"],
                "focused_query": query,
                "query_basis": basis,
                "baseline_hits": baseline["hits"],
                "focused_hits": [
                    {
                        "rank": h.rank,
                        "id": h.chunk_id,
                        "location": h.location.label,
                        "score": h.score,
                    }
                    for h in search.hits
                ],
            }
        )
    # Gold does not participate in query formation or ranking.
    gold = {
        (row["rejection"], row["claim"]): set(row["gold_paragraphs"])
        for row in read_jsonl(old / "score-rows.jsonl")
        if row["variant"] == "claim"
    }
    lines = [
        f"# {case} 차이 후보 중심 명세서 질의 비교",
        "",
        "BM25·색인·상위 10개·정답 고정. 차이 후보를 얻지 못하면 기존 질문을 재사용한다.",
        "",
    ]
    for row in rows:
        key = row["rejection"], row["claim"]
        labels = gold.get(key)
        row["gold"] = sorted(labels) if labels else None
        if labels:
            for variant in ("baseline", "focused"):
                hit_labels = [hit["location"] for hit in row[f"{variant}_hits"]]
                for k in (5, 10):
                    recall, mrr = metrics(labels, hit_labels, k)
                    row[f"{variant}_recall_at_{k}"] = recall
                    row[f"{variant}_mrr_at_{k}"] = mrr
        lines += [
            f"## 거절이유 {key[0]} · 청구항 {key[1]}",
            "",
            f"질의 근거 · {row['query_basis']}",
            "",
        ]
        for variant, title in (("baseline", "기존"), ("focused", "차이 후보")):
            lines += [f"**{title} 실제 질의**", "", "~~~~text", row[f"{variant}_query"], "~~~~", ""]
            locs = ", ".join(f"{h['rank']}위 {h['location']}" for h in row[f"{variant}_hits"])
            lines += [f"**{title} 검색 순위** {locs or '검색 결과 없음'}", ""]
        lines += [
            f"**기대 골드** {', '.join(row['gold']) if row['gold'] else '평정 문단 없음'}",
            "",
        ]
    write_jsonl(output / f"{case}.jsonl", rows)
    (output / f"{case}.md").write_text("\n".join(lines), encoding="utf-8")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cases = json.loads((args.source / "manifest.json").read_text())["cases"]
    settings = load_f3_settings()
    rows = [
        row for case in cases for row in run_case(args.source, case["case"], args.output, settings)
    ]
    scored = [row for row in rows if row["gold"]]
    summary = {
        "query_rows": len(rows),
        "scored_rows": len(scored),
        "query_basis": Counter(row["query_basis"] for row in rows),
        "scored_query_basis": Counter(row["query_basis"] for row in scored),
    }
    for variant in ("baseline", "focused"):
        for metric in ("recall", "mrr"):
            for k in (5, 10):
                key = f"{variant}_{metric}_at_{k}"
                summary[key] = mean(r[key] for r in scored)
        summary[f"{variant}_hits_at_10"] = sum(r[f"{variant}_recall_at_10"] > 0 for r in scored)
    summary["changed_scored_rows"] = sum(r["baseline_query"] != r["focused_query"] for r in scored)
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
