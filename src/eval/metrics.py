"""검색 평가 지표. 정답은 조문 단위로 판정한다(search-criteria.md 7-3).

chunk_id 형식: "법령명#제N조" (조문 청크) 또는 "법령명#제N조#제M항" (항 청크, Phase 3).
"""


def article_of(chunk_id: str) -> str:
    """chunk_id 에서 조문 id("법령명#제N조") 만 남긴다. 형식이 다르면 ValueError."""
    parts = [p.strip() for p in chunk_id.split("#")]
    if len(parts) < 2 or not parts[0] or not (parts[1].startswith("제") and "조" in parts[1]):
        raise ValueError(f"조문 id 형식이 아님: {chunk_id!r}")
    return "#".join(parts[:2])


def rank_of_gold(ranked_chunk_ids: list[str], gold: list[str] | tuple[str, ...],
                 max_rank: int | None = None) -> int | None:
    """정답 조문이 처음 나오는 순위(1부터). 같은 조문의 청크는 한 번만 센다. 없으면 None.

    정답이 여러 개면 그중 가장 높은 순위(H7 규칙). max_rank 가 있으면 그 순위(조문 기준) 밖은 None.
    """
    gold_set = {article_of(g) for g in gold}
    seen: list[str] = []
    for cid in ranked_chunk_ids:
        art = article_of(cid)
        if art in seen:
            continue
        seen.append(art)
        if art in gold_set:
            return len(seen)
        if max_rank is not None and len(seen) >= max_rank:
            return None
    return None


def hit_at_k(rank: int | None, k: int) -> bool:
    return rank is not None and rank <= k


def mrr(ranks: list[int | None]) -> float:
    if not ranks:
        return 0.0
    if any(r is not None and r < 1 for r in ranks):
        raise ValueError("순위는 1부터 시작해야 함")
    return sum(1.0 / r for r in ranks if r is not None) / len(ranks)


def summarize(ranks: list[int | None], ks: tuple[int, ...] = (1, 3, 5)) -> dict:
    """질문별 순위 목록 -> {"n", "hit@k"(적중 질문 수), "mrr"}."""
    out: dict = {"n": len(ranks)}
    for k in ks:
        out[f"hit@{k}"] = sum(hit_at_k(r, k) for r in ranks)
    out["mrr"] = mrr(ranks)
    return out
