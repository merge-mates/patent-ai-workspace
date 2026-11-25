"""Extract local source evidence and assemble independent citation/support checks."""

import argparse
import re
from collections import Counter
from hashlib import sha256
from pathlib import Path

from judge import anonymize, read_json, read_rows, write_json

PARA = re.compile(r"^\[(\d{4})\]\s*(.*)")
CLAIM_HEADING = re.compile(r"^청구항\s*(\d+)\.?$")
FIGURE = re.compile(r"^도면\s*(\d+\w?)$")
AMENDMENT_BASIS = "amendment_basis"


def pdf_pages(path):
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        return [(page.extract_text() or "").splitlines() for page in pdf.pages]


def plain(text):
    return re.sub(r"\s+", " ", text).strip()


def compact(text):
    return re.sub(r"[\s\u00ad]+", "", text).casefold()


def entry(source, loc, text, pages=None, edition=None):
    return {
        "source_id": f"{source}:{loc}",
        "source": source,
        "location": loc,
        "text": plain(anonymize(text)),
        "pages": pages or [],
        "edition": edition,
    }


def patent_source(path, source):
    pages = pdf_pages(path)
    groups = {}
    fallback = []
    current = None
    region = "front"
    for page, lines in enumerate(pages, 1):
        body = []
        for line in map(str.strip, lines):
            if not line or re.fullmatch(r"(공개|등록)특허\s+[\d-]+|-\s*\d+\s*-", line):
                continue
            if re.match(r"^\(57\)\s*요\s*약", line):
                region, current = "abstract", "요약"
            elif line.startswith(("청구범위", "특허청구의 범위")) or (
                CLAIM_HEADING.fullmatch(line) and region != "description"
            ):
                region, current = "claims", None
                if match := CLAIM_HEADING.fullmatch(line):
                    current = f"청구항 {int(match[1])}"
            elif line in {"명세서", "발명의 상세한 설명", "발명의 설명"}:
                region, current = "description", None
            elif match := PARA.match(line):
                region, current = "description", f"[{match[1]}]"
            elif match := FIGURE.fullmatch(line):
                region, current = "figures", f"도 {match[1].lower()}"
            if current:
                items = groups.setdefault(current, [])
                items.append((page, line))
            if region not in {"front", "figures"}:
                body.append(line)
        if body:
            fallback.append(entry(source, f"{page}쪽", " ".join(body), [page]))
    exact = [
        entry(source, label, " ".join(line for _, line in items), sorted({p for p, _ in items}))
        for label, items in groups.items()
    ]
    return exact + fallback


def build_corpus(repo, baseline, root, run):
    manifest = read_json(baseline / "manifest.json")
    for record in manifest["cases"]:
        case = record["case"]
        oa_path = repo / record["oa_pdf"]
        app = oa_path.parent.parent.name
        frozen = read_json(root / case / "oa-evidence.json")
        citations = {
            c["label"]: c["number"]
            for table in frozen["resolved_comparison_evidence"]
            for c in table["citations"]
        }
        sources = {}
        files = {}
        for label, number in sorted(citations.items()):
            path = repo / "data/raw/cited_v2" / app / f"{number}.pdf"
            files[label] = {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()}
            sources[label] = patent_source(path, label)
        spec_rows = read_rows(baseline / "spec-retrieval" / case / "paragraphs.jsonl")
        (spec_pdf,) = oa_path.parent.glob("*출원서*.pdf")
        files["SPEC"] = {"path": str(spec_pdf), "sha256": sha256(spec_pdf.read_bytes()).hexdigest()}
        files["OA"] = {"path": str(oa_path), "sha256": sha256(oa_path.read_bytes()).hexdigest()}
        paragraphs = {}
        for row in spec_rows:
            chunk = row["chunk"]
            if chunk["location"]["kind"] == "paragraph":
                label = chunk["location"]["label"]
                paragraphs.setdefault(label, []).append((row["page"], chunk["text"]))
        sources["SPEC"] = [
            entry("SPEC", label, " ".join(text for _, text in pieces), [page for page, _ in pieces])
            for label, pieces in paragraphs.items()
        ]
        sources["CLAIMS"] = [
            entry("CLAIMS", f"청구항 {row['claim']}", row["text"]) for row in frozen["claims_at_oa"]
        ]
        # Only frozen, source-backed legal excerpts. The original edition is part of the locator.
        law = {}
        for bundle in frozen["resolved_legal_evidence"]:
            for row in bundle["claims"]:
                for source in row["sources"]:
                    ev = source["evidence"]
                    if not ev["raw_text"]:
                        continue
                    loc = source["identifier"]
                    item = entry("LAW", loc, ev["raw_text"], edition=ev["edition"])
                    law[item["source_id"]] = item
        sources["LAW"] = list(law.values())
        issues = read_rows(root / "01-source-freeze/issues.jsonl")
        legitimate = {}
        for issue in issues:
            if issue["case"] != case:
                continue
            for loc in issue["oa_locations"]:
                legitimate.setdefault(loc["page"], set()).update(
                    range(loc["start_line"], loc["end_line"] + 1)
                )
        sources["OA"] = [
            entry(
                "OA",
                f"{row['page']}쪽",
                " ".join(
                    line
                    for n, line in enumerate(row["lines"], 1)
                    if n in legitimate.get(row["page"], set())
                ),
                [row["page"]],
            )
            for row in read_json(root / "01-source-freeze" / f"{case}-pages.json")
            if row["page"] in legitimate
        ]
        write_json(
            run / "source-catalog-local" / f"{case}.json", {"files": files, "sources": sources}
        )


def term_counts(text):
    return Counter(re.findall(r"[가-힣A-Za-z0-9×-]{2,}", text.casefold()))


def choose_candidates(corpus, query):
    counts = term_counts(query)
    scored = []
    for row in corpus:
        if row["source"] == "SPEC" and not row["location"].startswith("["):
            continue
        available = term_counts(row["text"])
        score = sum(min(n, available[token]) * min(6, len(token)) for token, n in counts.items())
        if score:
            scored.append((score, row))
    return [row for _, row in sorted(scored, key=lambda pair: -pair[0])[:3]]


def locator(check, sources):
    source = check["source"]
    locs = check["locations"]
    quoted = check.get("quoted")
    pages = check.get("pages") or []
    corpus = sources.get(source, [])
    if not locs:
        label = "no_citation"
        matches = []
    else:
        matches = [
            row
            for row in corpus
            if any(
                compact(loc)
                in {compact(row["location"]), compact(row["location"].removeprefix("특허법 "))}
                for loc in locs
            )
        ]
        labels_found = {compact(row["location"].removeprefix("특허법 ")) for row in matches}
        unresolved = {
            loc for loc in locs if compact(loc.removeprefix("특허법 ")) not in labels_found
        }
        if unresolved:
            # This catalog does not capture images or unnumbered prose; missing material is unknown.
            label = "partial" if matches else "unverifiable"
        elif pages and any(not set(pages).intersection(row["pages"]) for row in matches):
            label = "incorrect"
        elif (
            check.get("date")
            and source == "LAW"
            and any(
                not row.get("edition") or not in_edition(check["date"], row["edition"])
                for row in matches
            )
        ):
            label = "incorrect"
        elif quoted:
            terms = [compact(part) for part in re.split(r"…+|\.{3,}", quoted) if compact(part)]
            if not terms or not all(
                any(term in compact(row["text"]) for row in matches) for term in terms
            ):
                label = "quote_unverified"
            else:
                label = "accurate"
        else:
            label = "accurate"

    supplemental = []
    if not matches or label != "accurate" or check.get("seek_context"):
        if quoted:
            supplemental.extend(
                row
                for row in corpus
                if len(compact(quoted)) > 6 and compact(quoted) in compact(row["text"])
            )
        supplemental.extend(choose_candidates(corpus, check["proposition"]))
    matched_ids = {row["source_id"] for row in matches}
    selected = {}
    for row in matches + supplemental[:5]:
        if row["source_id"] not in selected:
            selected[row["source_id"]] = {
                **row,
                "match": "cited" if row["source_id"] in matched_ids else "context",
            }
    return label, list(selected.values())


def in_edition(day, edition):
    dates = re.findall(r"\d{4}-\d\d-\d\d", edition)
    if len(dates) == 2:
        return dates[0] <= day < dates[1]
    return bool(dates and dates[0] <= day)


def prepare_batches(run, size):
    for path in sorted((run / "response-raw").glob("*.json")):
        response = read_json(path)["parsed"]
        if response is None:
            continue
        original = read_json(run / "response-input" / path.name)
        sources = read_json(run / "source-catalog-local" / f"{path.stem[:3]}.json")["sources"]
        pending = []
        for row in response["issues"]:
            for check in row["checks"]:
                pending.append({**check, "issue_id": row["issue_id"], "type": "issue_evidence"})
        changes = {row["anchor"]: row for row in response["amendments"]}
        for amend in original["amendments"]:
            change = changes[amend["anchor"]]
            if change["state"] != "changed":
                continue
            for basis in amend["basis"]:
                pending.append(
                    {
                        "type": "amendment_citation",
                        "anchor": amend["anchor"],
                        "source": "SPEC",
                        "proposition": change["change"],
                        "locations": [basis["location"]] if basis["location"] else [],
                        "pages": [basis["page"]] if basis["page"] else [],
                        "quoted": basis["raw_text"],
                        "seek_context": True,
                    }
                )
            pending.append(
                {
                    "type": AMENDMENT_BASIS,
                    "anchor": amend["anchor"],
                    "source": "SPEC",
                    "proposition": change["change"],
                    "locations": sorted({b["location"] for b in amend["basis"] if b["location"]}),
                    "quoted": None,
                    "seek_context": True,
                }
            )
        checks = []
        for n, check in enumerate(pending, 1):
            position, evidence = locator(check, sources)
            anchor = check["anchor"]
            if check["type"] == AMENDMENT_BASIS:
                position = "not_applicable"
                existing_claims = sources["CLAIMS"]
                claim = int(anchor.removeprefix("A-"))
                evidence.extend(
                    {**row, "match": "oa_claim_context"}
                    for row in existing_claims
                    if row["location"] == f"청구항 {claim}"
                )
            checks.append(
                {
                    **check,
                    "check_id": f"E{n:03}",
                    "citation_position": position,
                    "evidence": evidence,
                    "draft_context": original["opinion_lines"].get(anchor)
                    or next((a for a in original["amendments"] if a["anchor"] == anchor), None),
                }
            )
        write_json(run / "source-checks-local" / path.name, checks)
        for n in range(0, len(checks), size):
            write_json(
                run / "support-input" / f"{path.stem}-{1 + n // size:02}.json",
                {
                    "checks": [
                        {k: v for k, v in c.items() if k != "citation_position"}
                        for c in checks[n : n + size]
                    ],
                },
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["corpus", "checks"])
    parser.add_argument("run", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--batch-size", type=int, default=18)
    args = parser.parse_args()
    if args.phase == "corpus":
        build_corpus(args.repo, args.baseline, args.root, args.run)
    else:
        prepare_batches(args.run, args.batch_size)


if __name__ == "__main__":
    main()
