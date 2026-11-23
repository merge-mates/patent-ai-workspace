"""Render the private four-OA evidence audit from saved artifacts, without model calls."""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from patent_ai.core.f3_claim_compare.textmatch import find_span, text_hash
from patent_ai.core.llm.json_answer import parse_answer


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def inline(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def block(label, value):
    return [label, "", "~~~~text", value, "~~~~", ""]


def spec_status(score):
    if score is None:
        return "골드 문단 라벨 없음"
    if score["unextracted_gold_paragraphs"]:
        return "골드 문단 추출 누락"
    if score["recall@10"] == 0:
        return "10위 내 전부 누락"
    if score["recall@5"] == 0:
        return "첫 정답 6–10위"
    if score["recall@10"] < 1:
        return "5위 내 적중·10위 내 일부 회수"
    return "5위 내 적중·10위 내 전부 회수"


def spec_report(run_dir, case, destination):
    stored = run_dir / "spec-retrieval" / case
    queries = read_jsonl(stored / "queries.jsonl")
    scores = {
        (row["variant"], row["rejection"], row["claim"]): row
        for row in read_jsonl(stored / "score-rows.jsonl")
    }
    chunks = {
        row["chunk"]["chunk_id"]: row["chunk"] for row in read_jsonl(stored / "paragraphs.jsonl")
    }
    by_location = defaultdict(list)
    for chunk in chunks.values():
        by_location[chunk["location"]["label"]].append(chunk["text"])

    lines = [
        f"# {case} 최초 명세서 검색",
        "",
        "검색 당시 질의, 결과 순위, 상세 골든셋의 문단 번호를 담았다. "
        "골드 문단이 표시되지 않은 행은 정확도 집계에서 제외한다.",
        "",
    ]
    counts = defaultdict(Counter)
    for q in queries:
        key = q["variant"], q["rejection"], q["claim"]
        score = scores.get(key)
        labels = score["gold_paragraphs"] if score else []
        status = spec_status(score)
        counts[q["variant"]][status] += 1
        lines += [f"## 거절이유 {q['rejection']} · 청구항 {q['claim']} · `{q['variant']}`", ""]
        lines += block("실제 질의", q["query"])
        lines += [f"**분류** {status}", ""]
        if labels:
            lines += [f"**기대 문단** {', '.join(labels)}", ""]
            for label in labels:
                text = " ".join(" ".join(by_location[label]).split())
                lines += [f"- `{label}` {inline(text[:180]) or '추출본에 없음'}"]
            lines.append("")
        lines += ["| 순위 | 쪽·문단 | BM25 | 결과 발췌 | 골드 |", "|---:|---|---:|---|---|"]
        for hit in q["hits"]:
            passage = " ".join(chunks[hit["id"]]["text"].split())
            gold = "일치" if hit["location"] in labels else ""
            lines.append(
                f"| {hit['rank']} | {hit['page']}쪽 {inline(hit['location'])} | "
                f"{hit['score']:.4f} | {inline(passage[:160])} | {gold} |"
            )
        if not q["hits"]:
            lines.append("| — | 검색 결과 없음 | — | — | — |")
        lines.append("")
    excluded = read_jsonl(stored / "excluded-rows.jsonl")
    if excluded:
        lines += ["## 검색 범위에서 제외한 골드 행", ""]
        for row in excluded:
            lines.append(
                f"- 거절이유 {row['rejection']} · 청구항 {row['claim']} · {row['reason']} · "
                f"{', '.join(row['gold_paragraphs'])}"
            )
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return counts


def cached_elements(cache_dir):
    output = defaultdict(set)
    for path in cache_dir.glob("*.json"):
        item = read_json(path)
        if not isinstance(item.get("text"), str):
            continue
        try:
            answer = parse_answer(item["text"], truncated=item.get("stop_reason") == "max_tokens")
        except json.JSONDecodeError:
            continue
        if not isinstance(answer, dict) or not isinstance(answer.get("elements"), list):
            continue
        if not isinstance(answer.get("claim"), int):
            continue
        for element in answer["elements"]:
            if isinstance(element, dict) and isinstance(element.get("text"), str):
                output[answer["claim"]].add(element["text"])
    return output


def other_searches(run_dir, case, dispatch, destination, citation_gold, elements):
    baseline = run_dir / "cli-baseline"
    (f3_path,) = (baseline / "f3").glob(f"*_{dispatch}.f3.json")
    (f2_path,) = (baseline / "f2").glob(f"*_{dispatch}.f2.json")
    f3, f2 = read_json(f3_path), read_json(f2_path)
    comparison = defaultdict(list)
    words = {}
    common_input = read_json(run_dir / "draft-comparison" / case / "common-input.json")
    for claim in common_input["claims_text"]:
        original = claim["text"]
        for element in elements[claim["claim"]]:
            span = find_span(element, original)
            if span:
                exact = original[span[0] : span[1]]
                words[text_hash(exact)] = exact
    for table in f3["comparisons"]:
        for row in table["rows"]:
            fingerprint = text_hash(row["element"])
            words[fingerprint] = row["element"]
            comparison[(table["unit_id"], row["claim"], row["citation"], fingerprint)].append(row)
    expected = defaultdict(set)
    for row in citation_gold:
        if row.get("exclude") or dispatch not in row["row_id"]:
            continue
        for doc in row["doc_ids"]:
            expected[doc].update(item["label"] for item in row["items"])

    missing_queries = 0
    lines = [
        "# 인용문헌 및 법률 검색 기록",
        "",
        "인용문헌 검색 로그는 구성요소 원문 대신 해시를 저장한다. 대비표 문구 또는 모델 캐시에서 "
        "청구항 원문에 맞춘 문구의 해시가 검색 로그와 일치할 때 실제 질의를 표시한다. "
        "문헌별 골드는 해당 OA의 청구항 수준 정답을 모은 참고 목록이다. "
        "2차는 이미 본 조각을 뺀 순서다.",
        "",
    ]
    for n, entry in enumerate(f3["search_log"], start=1):
        fingerprint = entry["element_hash"]
        query = words.get(fingerprint)
        missing_queries += query is None
        lines += [
            f"## 검색 {n} · 청구항 {entry['claim']} · {entry['citation']} · {entry['round']}차",
            "",
        ]
        lines += block("실제 질의", query or f"원문 복원 불가. 보존된 해시 {fingerprint}")
        lines += [
            f"**범위** {entry['searched_scope']}",
            "",
            "**문헌의 OA 골드 위치** "
            f"{', '.join(sorted(expected[entry['doc_id']])) or '매칭 없음'}",
            "",
        ]
        for index, chunk in enumerate(entry["hit_chunk_ids"], start=1):
            lines.append(f"{index}. `{chunk}`")
        if not entry["hit_chunk_ids"]:
            lines.append("검색 로그에 반환된 후보 없음.")
        lines.append("")
        for row in comparison[(entry["unit_id"], entry["claim"], entry["citation"], fingerprint)]:
            selected = [e.get("location") or str(e.get("page")) for e in row["evidence"]]
            lines += [
                f"**대비 결과** `{row['judgment']}` · `{row['status']['value']}` · "
                f"선택 위치 {', '.join(selected) or '없음'}",
                "",
            ]

    lines += [
        "# 법률 검색",
        "",
        "정식 조문 검색 골드가 없으며 로그에는 검색별 후보 수만 남았다. "
        "실제 법률 질문과 모델 결과에 남은 근거를 기록한다. 후보 순위는 복원할 수 없다.",
        "",
    ]
    for bundle in f2["bundles"]:
        question = bundle["question"]
        lines += [f"## {bundle['unit_id']}", ""]
        lines += block("실제 법률 질문", question["text"])
        lines += [
            f"적용 조문 {', '.join(question['article_refs']) or '확인되지 않음'} · "
            f"기준일 {question['as_of'] or '확인되지 않음'}",
            "",
            "| 출처 | 색인 | 호출 수 | 반환 수 | 상태 |",
            "|---|---|---:|---:|---|",
        ]
        for row in bundle["search_log"]:
            lines.append(
                f"| {row['source_kind']} | {row['index_version']} | {row['queries']} | "
                f"{row['hits']} | {row['status']['value']} |"
            )
        lines.append("")
        for claim in bundle["claims"]:
            identifiers = ", ".join(str(s["identifier"]) for s in claim["sources"])
            lines.append(f"- {claim['text']} ({identifiers})")
        lines.append("")
    destination.write_text("\n".join(lines), encoding="utf-8")
    return len(f3["search_log"]), missing_queries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--citation-gold", type=Path, required=True)
    args = parser.parse_args()
    root = args.run_dir
    cases = read_json(root / "manifest.json")["cases"]
    gold = read_jsonl(args.citation_gold)
    elements = cached_elements(root / "model-cache")
    reports = root / "query-audit"
    reports.mkdir(exist_ok=True)
    totals = defaultdict(Counter)
    index = [
        "# OA 네 건 실제 질의와 정답 대조",
        "",
        "| 사건 | 최초 명세서 상세 | 인용문헌·법률 상세 | 인용 검색 기록 | 해시만 남은 질의 |",
        "|---|---|---|---:|---:|",
    ]
    for row in cases:
        case = row["case"]
        spec_name, other_name = f"{case}-spec.md", f"{case}-cite-law.md"
        for variant, counts in spec_report(root, case, reports / spec_name).items():
            totals[variant].update(counts)
        searches, missing = other_searches(
            root, case, row["dispatch_number"], reports / other_name, gold, elements
        )
        index.append(
            f"| {case} | [실제 질의·상위 문단·골드]({spec_name}) | "
            f"[인용문헌·법률]({other_name}) | {searches} | {missing} |"
        )
    index += [
        "",
        "## 최초 명세서 질의별 분류",
        "",
        "| 결과 유형 | 청구항 원문 | 청구항 원문 + OA 설명 |",
        "|---|---:|---:|",
    ]
    for label in sorted(set(totals["claim"]) | set(totals["claim_and_oa"])):
        index.append(f"| {label} | {totals['claim'][label]} | {totals['claim_and_oa'][label]} |")
    index += [
        "",
        "[명세서 검색 지표](../spec-retrieval/summary.json) · "
        "[대응 방향과 명세서 근거 비교](../draft-comparison/audit.json) · "
        "[실험 계획](../experiment-plan.md)",
        "",
    ]
    (reports / "README.md").write_text("\n".join(index), encoding="utf-8")


if __name__ == "__main__":
    main()
