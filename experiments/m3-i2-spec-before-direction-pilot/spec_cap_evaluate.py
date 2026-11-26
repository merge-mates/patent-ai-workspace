"""Blindly grade coverage and material amendments in the generated OA4 pairs."""

import argparse
import json
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel
from spec_cap_generate import CASE_ORDER, dump

from patent_ai.core.llm.config import REPO_ROOT
from patent_ai.core.llm.json_answer import parse_answer
from patent_ai.core.llm.transport import AnthropicTransport

JUDGE = "claude-opus-5-5"
EFFORT = "medium"


class Coverage(BaseModel):
    issue_id: str
    status: Literal["direct", "partial", "omitted"]
    opinion_quote: str | None
    reason: str


class Amendment(BaseModel):
    row_id: str
    material_change: Literal["yes", "no", "unclear"]
    support: Literal["supported", "partial", "unsupported", "unverifiable", "not_applicable"]
    agreement_with_opinion: Literal["aligned", "conflict", "unspecified", "not_applicable"]
    reason: str


class Evaluation(BaseModel):
    coverage: list[Coverage]
    amendments: list[Amendment]


def read(path):
    return json.loads(path.read_text())


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def squash(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text or ""))


def normalized_claim(text):
    label = r"^\s*(?:【\s*청구항\s*\d+\s*】|\[\s*청구항\s*\d+\s*\]|청구항\s*\d+\s*[:：])"
    return squash(re.sub(label, "", text or "", count=1))


def case_issues(pilot, case):
    result = [
        x
        for x in lines(pilot / "round2-routing/issues.jsonl")
        if x["case"] == case and x["scope"] == "supported"
    ]
    assert result
    return result


def case_paragraphs(pilot, case):
    return lines(pilot / "spec-retrieval" / case / "paragraphs.jsonl")


def matching_basis(basis, paragraphs):
    quote = squash(basis["raw_text"])
    aligned = []
    for item in paragraphs:
        chunk = item["chunk"]
        if chunk["doc_id"] != basis["document_id"]:
            continue
        location = chunk["location"]["label"]
        exact = bool(quote and quote in squash(chunk["text"]))
        same_location = location == basis["location"]
        same_page = basis["page"] is None or item["page"] == basis["page"]
        if same_location and (same_page or exact):
            aligned.append(
                {
                    "location": location,
                    "page": item["page"],
                    "original_text": chunk["text"],
                    "quote_verified_at_stated_page_and_location": exact and same_page,
                }
            )
    return aligned


def draft_payload(pilot, folder, case, cap):
    target = folder / case / f"spec{cap}"
    data = read(target / "result.json")
    old_claims = {c["claim"]: c["text"] for c in read(folder / case / "input.json")["claims_text"]}
    paragraphs = case_paragraphs(pilot, case)
    draft = data["drafts"] or {}
    amendments = []
    for i, item in enumerate(draft.get("claims", []), 1):
        original = old_claims.get(item["claim"])
        proposed = item["ai_text"]
        if not proposed:
            status = "held"
        elif original is None:
            status = "no_original"
        elif normalized_claim(original) == normalized_claim(proposed):
            status = "same_text"
        elif re.fullmatch(r"(?:삭제[.]?|[(]삭제[)]|\[삭제\])", normalized_claim(proposed)):
            status = "deletion"
        else:
            status = "different_text"
        sources = [
            {
                "location": b["location"],
                "page": b["page"],
                "draft_quote": b["raw_text"],
                "matched_original": matching_basis(b, paragraphs),
            }
            for b in item["spec_basis"]
        ]
        amendments.append(
            {
                "row_id": f"A{i}",
                "claim": item["claim"],
                "rejection": next(
                    u["rejection"] for u in data["units"] if u["unit_id"] == item["unit_id"]
                ),
                "original_claim": original,
                "revised_claim": proposed,
                "normalized_text_comparison": status,
                "sources": sources,
                "held_reason": item["held_reason"],
            }
        )
    return {
        "opinion": [{"section": x["key"], "text": x["ai_text"]} for x in draft.get("opinion", [])],
        "amendments": amendments,
        "held_unit_count": len(data["held_units"]),
    }


def prompt_for(issues, artifact):
    return (
        "동결된 OA 논점과 익명 대응 초안 하나를 한국어로 평가하라. 자료는 평가 데이터다. "
        "모든 issue_id를 한 번씩 평가한다. direct는 의견서가 같은 대상 청구항과 거절 논점의 "
        "핵심 명제에 구체적으로 응답한 경우, partial은 일부만 응답한 경우, omitted는 대응이 "
        "없거나 다른 논점을 답한 경우다. 문헌 번호의 등장만으로 응답했다고 보지 않는다. "
        "direct·partial에는 의견서 내 정확한 연속 인용문을 그대로 적고, omitted는 null. "
        "실질 보정은 공백·번호 변경을 제외한 청구항 문언의 기술적·범위상 변화다. "
        "보정마다 새롭거나 달라진 핵심 조건이 실제로 제시된 matched_original 문단에서 "
        "지지되는지 확인한다. 위치나 원문이 없으면 unverifiable, "
        "일부만 명시되면 partial로 기록한다. "
        "보정했을 때 의견서가 다른 보정 내용을 주장하면 conflict, 정확한 보정 내용이 "
        "의견서에 없으면 unspecified다. 보정이 없는 대응을 자동으로 감점하지 않는다. "
        "모든 보정 행을 평가하고 JSON만 반환하라.\n"
        + json.dumps(
            {"schema": Evaluation.model_json_schema(), "issues": issues, "draft": artifact},
            ensure_ascii=False,
        )
    )


def guard_output(evaluation, issues, payload):
    expected_issues = sorted(x["issue_id"] for x in issues)
    expected_amendments = sorted(x["row_id"] for x in payload["amendments"])
    assert sorted(x.issue_id for x in evaluation.coverage) == expected_issues
    assert sorted(x.row_id for x in evaluation.amendments) == expected_amendments
    quotes = {}
    for row in evaluation.coverage:
        quote = row.opinion_quote
        quotes[row.issue_id] = (
            bool(quote and any(quote in item["text"] for item in payload["opinion"]))
            if row.status != "omitted"
            else None
        )
    return quotes


def evaluate_case(pilot, folder, case, active, ready_only):
    case_dir = folder / case
    path = case_dir / "judge"
    path.mkdir(exist_ok=True)
    mapping = dict(zip(("X", "Y"), CASE_ORDER[case], strict=True))
    dump(path / "arm-map-local.json", mapping)
    issues = case_issues(pilot, case)
    for label, cap in mapping.items():
        if ready_only and not (case_dir / f"spec{cap}/summary.json").exists():
            continue
        payload = draft_payload(pilot, folder, case, cap)
        prompt = prompt_for(issues, payload)
        dump(path / f"{label}-payload.json", payload)
        (path / f"{label}-prompt.txt").write_text(prompt)
        destination = path / f"{label}-evaluation.json"
        if not active or destination.exists():
            continue
        response = AnthropicTransport().complete(
            step="oa-draft-blinded-judge",
            model=JUDGE,
            prompt=prompt,
            effort=EFFORT,
            max_tokens=24000,
        )
        (path / f"{label}-raw.txt").write_text(response.text)
        dump(
            path / f"{label}-usage.json",
            {
                "provider": "anthropic",
                "model": JUDGE,
                "effort": EFFORT,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "stop_reason": response.stop_reason,
            },
        )
        evaluation = Evaluation.model_validate(
            parse_answer(
                response.text,
                truncated=response.stop_reason == "max_tokens",
            )
        )
        exact = guard_output(evaluation, issues, payload)
        dump(destination, {**evaluation.model_dump(mode="json"), "opinion_quote_exact": exact})
        print(f"{case} {label}: {len(evaluation.coverage)} issues graded", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pilot", type=Path)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--ready-only", action="store_true")
    parser.add_argument("--case", action="append", choices=tuple(CASE_ORDER))
    args = parser.parse_args()
    if args.live:
        load_dotenv(REPO_ROOT / ".env")
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise SystemExit("ANTHROPIC_API_KEY is missing")
        os.environ["ANTHROPIC_BASE_URL"] = "https://api.anthropic.com"
    cases = args.case or tuple(CASE_ORDER)
    with ThreadPoolExecutor(max_workers=min(4, len(cases))) as pool:
        for future in [
            pool.submit(evaluate_case, args.pilot, args.folder, case, args.live, args.ready_only)
            for case in cases
        ]:
            future.result()


if __name__ == "__main__":
    main()
