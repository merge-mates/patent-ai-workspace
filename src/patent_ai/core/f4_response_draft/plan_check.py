"""사건 단위 보정안(E 실험의 보정 청구항 묶음) 코드 검사. 모델 호출 없음.

합친 흐름 실험(이 브랜치)용. 앱 보정 단계는 모델이 준 명세서 근거를 원문과 대조하고 묶음 밖
청구항을 막는다. E 보정안은 근거 위치를 주지 않으므로, 대신 코드로 두 가지만 표시한다.
고치지 않고, 적법성(신규사항 등)을 판정하지 않는다.
- dangling_reference: 지운 청구항을 아직 인용하는 남은 청구항 (인용 번호 정리 빠짐)
- not_in_source: 새로 쓴 문구 조각 중 명세서와 OA 당시 청구항 어디에서도 거의 못 찾은 것
"""

import re

from pydantic import BaseModel, ConfigDict

GRAM = 6  # 글자 조각 길이 (띄어쓰기 뺌)
MIN_CHARS = 10  # 이보다 짧은 문구 조각은 어디든 맞아 보지 않는다
MIN_FOUND = 0.5  # 조각의 6글자 묶음 중 원문에서 찾은 비율이 이보다 낮으면 표시

_REF = re.compile(r"(?:제\s*(\d+)\s*항|청구항\s*(\d+))")
_SPLIT = re.compile(r"[;,\n]")


class PlanIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str  # dangling_reference | not_in_source
    claim: int
    detail: str  # 인용하는 지운 항 번호, 또는 못 찾은 문구 조각


def _bare(text: str) -> str:
    return re.sub(r"\s", "", text)


def _grams(text: str) -> set[str]:
    return {text[i : i + GRAM] for i in range(max(0, len(text) - GRAM + 1))}


def check_plan(old: dict[int, str], plan: list[dict], spec_text: str) -> list[PlanIssue]:
    """old: OA 당시 청구항 번호 → 글. plan: [{claim, action(amend|delete|add), text}]."""
    deleted = {q["claim"] for q in plan if q["action"] == "delete"}
    after = dict(old)
    for q in plan:
        if q["action"] == "delete":
            after.pop(q["claim"], None)
        else:
            after[q["claim"]] = q["text"]
    issues: list[PlanIssue] = []
    for n in sorted(after):
        refs = {int(a or b) for a, b in _REF.findall(after[n])}
        for gone in sorted(refs & deleted):
            issues.append(PlanIssue(kind="dangling_reference", claim=n, detail=str(gone)))
    source = _grams(_bare(spec_text + "".join(old.values())))
    for q in sorted(plan, key=lambda q: q["claim"]):
        if q["action"] == "delete":
            continue
        for piece in _SPLIT.split(q["text"]):
            bare = _bare(_REF.sub("", piece))  # 인용 번호("제1항 또는 제3항")는 문구가 아니다
            if len(bare) < MIN_CHARS:
                continue
            grams = _grams(bare)
            if sum(g in source for g in grams) / len(grams) < MIN_FOUND:
                issues.append(
                    PlanIssue(kind="not_in_source", claim=q["claim"], detail=piece.strip())
                )
    return issues
