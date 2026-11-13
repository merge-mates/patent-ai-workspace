"""검색 결과(조문 id 순위 목록) 후처리: 법령 간 경쟁을 다루는 두 가지 규칙 (Phase 6 실험 ③).

규칙은 결과를 보기 전에 고정했다(숫자 파라미터 없이 top_k·window 만, 개발 결과를 보고 고치지 않는다).
- law_first: 상위 top_k 안에서 특허법 조문을 앞으로 보낸다(안정 정렬, 순서는 유지).
- link_pairs: 상위 lead_k 조문 각각에 대해, 그 조문과 서로 인용하는 짝(법 ↔ 시행령·시행규칙)이 상위 window 안에 있으면
  가장 높은 순위의 짝 하나를 바로 뒤로 올린다. 새로운 조문을 가져오지 않고 이미 나온 후보의 순서만 바꾼다.
조문 id 형식: "특허법#제29조", "특허법 시행령#제5조", "특허법 시행규칙#제16조".
"""
import re
from collections import defaultdict

from src.eval.metrics import article_of

_LAW_REF = re.compile(r"(?:(?<![가-힣])법|특허법」?)\s*제(\d+)조(?:의(\d+))?")
_DECREE_REF = re.compile(r"(?<![가-힣])영\s*제(\d+)조(?:의(\d+))?")


def law_of(article_id: str) -> str:
    return article_id.split("#")[0]


def law_first(ranked: list[str], top_k: int = 10) -> list[str]:
    head, tail = ranked[:top_k], ranked[top_k:]
    return [a for a in head if law_of(a) == "특허법"] + [a for a in head if law_of(a) != "특허법"] + tail


def _ref_id(law: str, m: re.Match) -> str:
    return f"{law}#제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")


def build_links(chunks: list[dict]) -> dict[str, set[str]]:
    """조문 id -> 서로 인용하는 조문 id 집합(양방향). 시행령·시행규칙 본문의 '법 제N조'(특허법)와
    시행규칙 본문의 '영 제N조'(특허법 시행령)를 따라간다. 코퍼스에 없는 조문은 무시한다."""
    text: dict[str, list[str]] = defaultdict(list)
    for c in chunks:
        text[article_of(c["chunk_id"])].append(c["text"])
    exists = set(text)
    links: dict[str, set[str]] = defaultdict(set)
    for art, parts in text.items():
        law = law_of(art)
        if law == "특허법":
            continue
        body = "\n".join(parts)
        targets = [_ref_id("특허법", m) for m in _LAW_REF.finditer(body)]
        if law == "특허법 시행규칙":
            targets += [_ref_id("특허법 시행령", m) for m in _DECREE_REF.finditer(body)]
        for t in targets:
            if t in exists and t != art:
                links[art].add(t)
                links[t].add(art)
    return links


def link_pairs(ranked: list[str], links: dict[str, set[str]], lead_k: int = 3, window: int = 10) -> list[str]:
    head, tail = ranked[:window], ranked[window:]
    lead = set(head[:lead_k])
    out: list[str] = []
    placed: set[str] = set()
    for a in head:
        if a in placed:
            continue
        out.append(a)
        placed.add(a)
        if a in lead:
            partner = next((p for p in head if p in links.get(a, ()) and p not in placed), None)
            if partner:
                out.append(partner)
                placed.add(partner)
    return out + tail


def apply_rerank(name: str, ranked: list[str], links: dict[str, set[str]] | None = None) -> list[str]:
    if name == "none":
        return ranked
    if name == "law_first":
        return law_first(ranked)
    if name == "link_pairs":
        return link_pairs(ranked, links or {})
    raise ValueError(f"알 수 없는 후처리: {name}")
