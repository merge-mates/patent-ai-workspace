"""의견서 코드 검사 (모델 없이, 11/26 지시문 6절).

- 종속항 처리 일치율: 처리 논점(반박 논점이 아닌 종속항)마다 실제 처리 = 초안 처리인가
- 보정 항 언급률: 보정 결과의 바뀐·지운 항 가운데 보정 설명이 번호로 언급한 비율
- 심사관 위치 인용률: 반박 논점 가운데 심사관이 그 항에 든 문단을 초안이 하나라도 짚은 비율
초안 처리는 보정 설명의 항 번호 + 삭제/합침 말, 반박의 "종속항 역시" 꼴 문장으로 정한다.
"""

import re
from dataclasses import dataclass

from eval.opinion.text import bundle_covers, clauses, mentioned_claims, squash

_DELETE = re.compile(r"삭제")
_MERGE = re.compile(r"병합|합쳐|합하|합침|부가|삽입|편입|포함시|추가하|이동|반영")


@dataclass(frozen=True)
class DraftText:
    """초안 글자 두 칸. 실제 의견서를 초안 자리에 넣을 때는 두 칸 다 의견서 전체 글."""

    amendment: str  # 보정 설명
    response: str  # 대응과 근거 (반박)


def draft_treatment(claim: int, draft: DraftText) -> str:
    """초안이 그 항을 어떻게 처리했나 (삭제 / 합침 / 자체 보정 / 묶음 처리 / 언급 없음)."""
    said = [s for s in clauses(draft.amendment) if claim in mentioned_claims(s)]
    flat = [squash(s) for s in said]
    if any(_MERGE.search(s) for s in flat):
        # "제4항을 삭제하고 그 구성을 제1항에 부가" = 합침 (삭제 말이 같이 있어도)
        return "합침"
    if any(_DELETE.search(s) for s in flat):
        return "삭제"
    if said:
        return "자체 보정"
    if bundle_covers(draft.response, claim):
        return "묶음 처리"
    return "언급 없음"


def treatment_agreement(issues: list[dict], draft: DraftText) -> tuple[int, int, list[dict]]:
    """(맞은 수, 처리 논점 수, 줄마다 {id, claim, actual, draft, hit})."""
    rows = []
    for x in issues:
        if x["role"] != "처리":
            continue
        got = draft_treatment(x["claim"], draft)
        rows.append(
            {"id": x.get("id"), "claim": x["claim"], "actual": x["actual"], "draft": got,
             "hit": got == x["actual"]}
        )  # fmt: skip
    return sum(r["hit"] for r in rows), len(rows), rows


def amended_mention_rate(changed: list[int], draft: DraftText) -> tuple[int, int]:
    """(보정 설명이 번호로 언급한 바뀐·지운 항 수, 바뀐·지운 항 수)."""
    said = mentioned_claims(draft.amendment)
    return sum(1 for c in changed if c in said), len(changed)


_PARA = re.compile(
    r"[【\[(]\s*(\d{4,5})\s*[】\])](?:\s*[-~]\s*[【\[(]?\s*(\d{4,5})\s*[】\])]?)?"
    r"|식별번호\s*\[?\s*(\d{1,5})|단락\s*\[?\s*(\d{3,5})"
)


def paragraph_numbers(text: str) -> set[int]:
    """글에 나온 문단 번호 ([0022]-[0025]는 22~25 모두)."""
    out: set[int] = set()
    for m in _PARA.finditer(text):
        a, b, c, d = m.groups()
        if a:
            lo = int(a)
            hi = int(b) if b else lo
            out |= set(range(lo, hi + 1)) if lo <= hi < lo + 300 else {lo}
        else:
            out.add(int(c or d))
    return out


def examiner_location_hit(locations: dict[str, list[str]], response: str) -> bool | None:
    """심사관이 든 문단을 초안이 하나라도 짚었나. 심사관 위치에 문단이 없으면 None (셈 밖)."""
    gold = set()
    for labels in locations.values():
        for label in labels:
            gold |= paragraph_numbers(label)
    if not gold:
        return None
    return bool(gold & paragraph_numbers(response))
