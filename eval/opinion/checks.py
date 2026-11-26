"""의견서 코드 검사 (모델 없이, 11/26 지시문 6절).

- 종속항 처리 일치율: 처리 논점(반박 논점이 아닌 종속항)마다 실제 처리 = 초안 처리인가
- 보정 항 언급률: 보정 결과의 바뀐·지운 항 가운데 보정 설명이 번호로 언급한 비율
- 심사관 위치 인용률: 반박 논점 가운데 심사관이 그 항에 든 문단을 초안이 하나라도 짚은 비율
초안 처리는 보정 설명의 항 번호 + 삭제/합침 말, 반박의 "종속항 역시" 꼴 문장으로 정한다.
"""

import re
from dataclasses import dataclass

from eval.opinion.text import (
    LIST,
    bundle_covers,
    clauses,
    expand,
    mentioned_claims,
    sentences,
    squash,
    strip_quotes,
)

# 청구항을 지웠다는 말 (글자를 지우는 "'상기'를 단순 삭제하면"은 아님)
_DELETE = re.compile(
    r"항(을|은|는|이|도)?(모두)?삭제|\(삭제|:삭제|삭제(하였|했|되었|됐|함|됨|합니다|하고|하며|된|한|처리)"
)
_MERGE = re.compile(r"병합|합쳐|합쳤|합친|합하|합침|부가|삽입|편입|포함시|추가하|이동|반영")
# 바꾸지 않았다는 말: 그 항을 언급해도 보정 설명이 아니다
_NOT_CHANGED = re.compile(
    r"(보정|변경|수정|정정)(하지|되지|을하지|이)?않|그대로|(변경|보정|수정|바뀐것)이?없|바뀌지않|unchanged"
    r"|전후(가)?동일|동일(합니다|함|하다|하게)"
)


# 줄 머리 "- 청구항 4, 5: …", "- 제3항: …" (그 줄은 머리 번호 항을 말한다)
_HEAD = re.compile(rf"^\s*[-•*·]?\s*(?:청구항\s*)?(?:제\s*)?({LIST})\s*항?\s*:(.*)$")
# 머리표 뒤가 처리 말로 바로 시작하면 표 줄이다 ("- 제4항: 삭제", "- 제2항: 보정")
_TAG_WORD = re.compile(r"(보정|정정|수정|바뀜|삭제|합침|병합|그대로)")


@dataclass(frozen=True)
class DraftText:
    """초안 글자 두 칸. 실제 의견서를 초안 자리에 넣을 때는 두 칸 다 의견서 전체 글."""

    amendment: str  # 보정 설명
    response: str  # 대응과 근거 (반박)


_CHANGED = re.compile(r"보정|한정|부가|추가|정정|수정|바뀌|바꾸|바꿨|바뀐|변경|명확|고쳤|고침")


def _verdict(text: str) -> str | None:
    """마디 하나의 처리 말: 합침 > 삭제 > 그대로(바꾸지 않음) > 자체 보정. 동사가 없으면 None."""
    flat = squash(text)
    if _MERGE.search(flat):
        return "합침"
    if _DELETE.search(flat):
        return "삭제"
    if _NOT_CHANGED.search(flat):
        return "그대로"
    if _CHANGED.search(flat):
        return "자체 보정"
    return None


def _tag_verdict(rest: str) -> str:
    """표 줄·꼬리표의 처리 말 ("삭제", "삭제 (청구항 1에 합침)", "보정", "그대로")."""
    flat = squash(rest)
    if _NOT_CHANGED.search(flat):  # "보정 결과에서 변경되지 않았습니다"는 표 줄 '보정'이 아니다
        return "그대로"
    if _MERGE.search(flat):
        return "합침"
    if flat.startswith("삭제"):
        return "삭제"
    if flat.startswith("그대로"):
        return "그대로"
    return "자체 보정"


def draft_treatment(claim: int, draft: DraftText) -> str:
    """초안이 그 항을 어떻게 처리했나 (삭제 / 합침 / 자체 보정 / 묶음 처리 / 언급 없음).

    보정 설명을 줄 → 문장 → 마디로 나눠, 그 항 번호가 (따옴표 밖에) 나온 마디의 말로 정한다.
    동사 없는 조각("제14항 및 제2~10항,")은 같은 문장 뒤쪽 마디의 말을 따른다.
    """
    found: list[tuple[bool, str]] = []  # (그 항만 말한 마디인가, 처리 말)
    tags: set[str] = set()  # 표 줄 머리표 "- 제4항: 삭제"·꼬리표 "제12항(보정)"의 처리 말
    for line in draft.amendment.split("\n"):
        head = _HEAD.match(strip_quotes(line))
        if head:
            heads = set(expand(head.group(1)))
            # "- 청구항 3: 청구항 2에 …" 줄의 2항은 인용 관계일 뿐
            # → 머리 번호가 아닌 항은 이 줄을 건너뛴다
            if claim not in heads:
                continue
            rest = head.group(2).strip()
            if _TAG_WORD.match(rest):
                tags.add(_tag_verdict(rest))
        for sent in sentences(line):
            # 따옴표 안(청구항 글자 인용)은 문장째 먼저 뺀다 (마디로 나누면 따옴표가 쪼개짐)
            parts = clauses(strip_quotes(sent))
            for i, part in enumerate(parts):
                nums = mentioned_claims(strip_quotes(part))
                if claim not in nums:
                    continue
                # 항 번호 바로 뒤 꼬리표 "제12항(보정)", "청구항 15 (삭제)"가 있으면 그것을 따른다
                tag = re.search(
                    rf"(?<!\d){claim}\s*항?\s*[(\[]\s*(보정|정정|수정|바뀜|삭제|합침|병합)", part
                )
                v = None
                if tag:
                    v = _verdict(tag.group(1))
                    tags.add(_tag_verdict(tag.group(1)))
                for later in parts[i:] if v is None else []:
                    v = _verdict(strip_quotes(later))
                    if v is not None:
                        break
                # 뒤에 말이 없으면 앞 마디를 본다 ("변경되지 않은 항: 제2항 내지 제10항, 제14항")
                for earlier in reversed(parts[:i]) if v is None else []:
                    v = _verdict(strip_quotes(earlier))
                    if v is not None:
                        break
                found.append((len(nums) <= 2, v or "자체 보정"))
    all_kinds = {v for _, v in found}
    # 머리표·꼬리표가 있으면 그것이 보정 결과다
    # (보정된 항을 "…추가했습니다" 설명 때문에 합침으로 읽지 않게)
    if tags:
        kinds = list(tags)
    else:
        # 여러 항을 나열한 요약 마디보다 그 항만(두 항까지) 말한 마디를 따른다
        if any(specific for specific, _ in found):
            found = [f for f in found if f[0]]
        kinds = [v for _, v in found]
    # 합친 항은 늘 지운 항이기도 하다: 그 항만 말한 마디가 '삭제'여도 다른 마디(여러 항 나열)가
    # '합쳤다'고 하면 합침으로 본다 (코드가 만든 표 줄 "- 제4항: 삭제"가 합침 설명을 이기지 않게)
    if "삭제" in kinds and "합침" in all_kinds:
        return "합침"
    for kind in ("합침", "삭제", "자체 보정"):
        if kind in kinds:
            return kind
    if bundle_covers(draft.response, claim):
        return "묶음 처리"
    return "언급 없음"


def _agrees(actual: str, got: str) -> bool:
    """실제 처리 = 초안 처리. 단 실제 의견서가 언급하지 않은 종속항을 초안이 묶음 문장으로 다룬 것은
    맞음으로 센다 (11/26 재아 결정: 초안이 더 완전한 것을 감점하지 않음)."""
    return got == actual or (actual == "언급 없음" and got == "묶음 처리")


def treatment_agreement(issues: list[dict], draft: DraftText) -> tuple[int, int, list[dict]]:
    """(맞은 수, 처리 논점 수, 줄마다 {id, claim, actual, draft, hit})."""
    rows = []
    for x in issues:
        if x["role"] != "처리":
            continue
        got = draft_treatment(x["claim"], draft)
        rows.append(
            {"id": x.get("id"), "claim": x["claim"], "actual": x["actual"], "draft": got,
             "hit": _agrees(x["actual"], got)}
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
