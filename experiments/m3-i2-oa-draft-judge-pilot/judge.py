"""Prepare and execute blinded OA response and source judgements."""

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL = "gpt-4.1-2025-04-14"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_rows(path, rows):
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )


def anonymize(text):
    text = re.sub(r"\b(?:\d{10,15}_){1,2}\d{10,15}\b", "[사건ID]", text)
    return re.sub(
        r"(?<![\dA-Z])(?:\d{10,15}|\d{2}-\d{4}-\d{7}|9-5-\d{4}-\d{9})(?!\d)", "[사건ID]", text
    )


def prepare_responses(root, run):
    freeze = read_json(root / "01-source-freeze/freeze.json")
    issues_path = root / "01-source-freeze/issues.jsonl"
    if sha256(issues_path.read_bytes()).hexdigest() != freeze["issues_sha256"]:
        raise ValueError("Frozen OA issues changed")
    issues = read_rows(issues_path)
    for folder in sorted(root.glob("C[0-9][0-9]")):
        case = folder.name
        evidence = read_json(folder / "oa-evidence.json")
        for draft in read_json(folder / "drafts-blinded.json"):
            alias = draft["draft"].split()[-1]
            lines = {}
            for sec_no, section in enumerate(draft["opinion"], 1):
                if section["section"] == "사건 정보":
                    continue
                for line_no, line in enumerate(section["text"].splitlines(), 1):
                    if line.strip():
                        lines[f"O{sec_no}-L{line_no:02}"] = line
            amendments = []
            for amend in draft["amendments"]:
                amendments.append(
                    {
                        "anchor": f"A-{amend['claim']}",
                        "original": amend["original"],
                        "draft_text": amend["draft_text"],
                        "held_reason": amend["held_reason"],
                        "basis": [
                            {key: ref[key] for key in ("page", "location", "raw_text")}
                            for ref in amend["basis"]
                        ],
                    }
                )
            payload = {
                "issues": [row for row in issues if row["case"] == case],
                "opinion_lines": lines,
                "amendments": amendments,
                "claims_at_oa": {
                    str(row["claim"]): row["text"] for row in evidence["claims_at_oa"]
                },
            }
            for row in payload["issues"]:
                for location in row["oa_locations"]:
                    location["quote"] = anonymize(location["quote"])
            payload = json.loads(anonymize(json.dumps(payload, ensure_ascii=False)))
            write_json(run / "response-input" / f"{case}-{alias}.json", payload)


def validate_response(result, data):
    if [r["issue_id"] for r in result["issues"]] != [r["issue_id"] for r in data["issues"]]:
        raise ValueError("Wrong issue sequence")
    if [r["anchor"] for r in result["amendments"]] != [r["anchor"] for r in data["amendments"]]:
        raise ValueError("Wrong amendment sequence")
    anchors = set(data["opinion_lines"]) | {r["anchor"] for r in data["amendments"]}
    for row in result["issues"]:
        if row["response"] not in {"direct", "partial", "omitted", "unassessable"}:
            raise ValueError("Invalid response label")
        if not set(row["anchors"]) <= anchors or not row["reason"]:
            raise ValueError("Invalid anchor or empty reason")
        if row["response"] in {"direct", "partial"} and not row["anchors"]:
            raise ValueError("Missing response anchors")
        if any(check["anchor"] not in anchors for check in row["checks"]):
            raise ValueError("Invalid check anchor")
    for row in result["amendments"]:
        if row["state"] not in {"changed", "deleted", "held", "unchanged"} or row[
            "cross_document"
        ] not in {
            "consistent",
            "inconsistent",
            "unassessable",
        }:
            raise ValueError("Invalid amendment label")


def validate_support(result, data):
    if [r["check_id"] for r in result["checks"]] != [r["check_id"] for r in data["checks"]]:
        raise ValueError("Wrong check sequence")
    for row, check in zip(result["checks"], data["checks"], strict=True):
        if row["support"] not in {
            "supported",
            "partial",
            "unsupported",
            "contradicted",
            "unverifiable",
        }:
            raise ValueError("Invalid support label")
        source = {entry["source_id"]: entry["text"] for entry in check["evidence"]}
        for quote in row["quotes"]:
            if (
                quote["source_id"] not in source
                or quote["text"] not in source[quote["source_id"]]
                or not quote["text"].strip()
            ):
                raise ValueError(f"Invalid source excerpt {row['check_id']}")
        if row["support"] != "unverifiable" and not row["quotes"]:
            raise ValueError("Missing source quote")


def execute(folder, phase, env, workers, only):
    from dotenv import dotenv_values
    from openai import OpenAI

    if phase == "response":
        validate = validate_response
    else:
        validate = validate_support
    client = OpenAI(api_key=dotenv_values(env)["OPENAI_API_KEY"], timeout=240, max_retries=0)
    prompt = (HERE / f"{phase}-prompt.md").read_text(encoding="utf-8")
    write_json(folder / f"{phase}-prompt.json", {"model": MODEL, "instructions": prompt})

    def call(path):
        destination = folder / f"{phase}-raw" / path.name
        input_hash = sha256(path.read_bytes()).hexdigest()
        data = read_json(path)
        attempts = []
        if destination.exists():
            previous = read_json(destination)
            if previous["input_sha256"] != input_hash:
                raise ValueError(f"Use a fresh run folder for changed input: {path.name}")
            if previous.get("parsed") is not None:
                return
            attempts = previous["attempts"]
        input_text = path.read_text(encoding="utf-8")
        repair = ""
        for _ in range(3):
            started = time.monotonic()
            attempt = {}
            try:
                response = client.responses.create(
                    model=MODEL,
                    instructions=prompt + repair,
                    input=input_text,
                    text={"format": {"type": "json_object"}},
                    max_output_tokens=15500,
                    temperature=0,
                    store=False,
                )
                attempt.update(response.model_dump(mode="json"))
                result = json.loads(response.output_text)
                validate(result, data)
                break
            except Exception as error:
                attempt["error"] = (
                    str(error)
                    if isinstance(error, (ValueError, KeyError))
                    else type(error).__name__
                )
                repair = (
                    "\n직전 출력 검증 오류를 바로잡아 모든 ID와 인용 문자열을 정확히 반환한다. "
                    + attempt["error"]
                )
                result = None
            finally:
                attempt["elapsed_seconds"] = round(time.monotonic() - started, 3)
                attempts.append(attempt)
                write_json(
                    destination,
                    {
                        "input_sha256": input_hash,
                        "parsed": result,
                        "attempts": attempts,
                    },
                )
        print(phase, path.stem, "OK" if result else "FAILED", flush=True)

    paths = sorted((folder / f"{phase}-input").glob("*.json"))
    if only:
        paths = [path for path in paths if path.stem.startswith(only)]
    if not paths:
        raise ValueError("No matching judge input files")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(call, paths))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare-response", "response", "support"])
    parser.add_argument("root", type=Path)
    parser.add_argument("run", type=Path)
    parser.add_argument("--env", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--only")
    args = parser.parse_args()
    if args.phase == "prepare-response":
        prepare_responses(args.root, args.run)
    else:
        if args.env is None:
            parser.error("--env is required for model calls")
        execute(args.run, args.phase, args.env, args.workers, args.only)


if __name__ == "__main__":
    main()
