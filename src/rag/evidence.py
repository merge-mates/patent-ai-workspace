"""근거 단위: 검색된 조문 하나 = 근거 하나(꼬리표 E1, E2, …). 생성·검증·평가가 같은 단위를 쓴다."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Evidence:
    tag: str            # "E1".."E5" — 모델이 인용할 때 쓰는 꼬리표(법령 이름이 겹치는 문제를 피함)
    article_id: str     # "특허법#제29조", "특허법 시행령#제5조"
    label: str          # 사람이 읽는 이름: "특허법 제29조"
    text: str           # 조문 전체 글(max_chars 에서 잘림)
    truncated: bool


def build_evidence(ranked: list[str], full_texts: dict[str, str], n: int = 5,
                   max_chars: int = 4000) -> list[Evidence]:
    """재순위된 조문 id 목록 -> 앞에서 n개 근거. 중복 id 는 건너뛰고, 긴 글은 max_chars 에서 자른다."""
    if n <= 0:
        return []
    out: list[Evidence] = []
    seen: set[str] = set()
    for art in ranked:
        if art in seen:
            continue
        seen.add(art)
        text = full_texts[art]
        out.append(Evidence(tag=f"E{len(out) + 1}", article_id=art, label=art.replace("#", " "),
                            text=text[:max_chars], truncated=len(text) > max_chars))
        if len(out) == n:
            break
    return out
