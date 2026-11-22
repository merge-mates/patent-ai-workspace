"""진보성 요약의 효과 반박 후보 (F3 ③): 차이점 구성요소의 효과 문장을 최초 명세서에서 뽑는다.

- 효과 문장을 고르는 것은 모델 1회(프롬프트 prompts/f3/effect.md)이고, 후보 조각은 그 사건 출원서를
  메모리 BM25로 차이점마다 상위 k개(config/f3.yaml effect_search.k) 받는다 (명확성과 같은 색인).
- 코드가 확인한다: 모델이 옮긴 문장이 명세서 글에 그대로 있는가 (공백 줄이기만 허용).
  모델이 고른 조각에 없으면 명세서 전체(모든 조각, 쪽을 넘어 이어진 문단 포함)에서 한 번 더 찾는다.
  그래도 없으면 후보에서 뺀다 (근거를 지어내지 않는다). 뺀 건수는 부르는 쪽이 보류로 남긴다.
- 효과 문장은 심사관 판단을 반박할 후보일 뿐이다. 진보성이 있다는 결론을 내지 않는다.
"""

import json
import logging
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from patent_ai.core.f3_claim_compare.clarity import SpecChunk, SpecIndex
from patent_ai.core.f3_claim_compare.inputs import F3Config
from patent_ai.core.f3_claim_compare.retry import call_checked
from patent_ai.core.f3_claim_compare.textmatch import find_span, is_too_short
from patent_ai.core.llm.limits import RunContext

logger = logging.getLogger(__name__)

STEP = "f3.effect"


# ---- 모델이 돌려주는 출력 스키마 ----
class EffectPick(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    difference_no: int
    chunk_id: str  # 후보 조각 ID
    quote: str  # 그 조각 글에서 그대로 옮긴 효과 문장


class EffectAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    effects: list[EffectPick] = []


@dataclass(frozen=True)
class Difference:
    """효과를 찾을 차이점 구성요소 하나. no는 모델에 보여 주는 번호."""

    no: int
    location: str  # 청구항 안 위치 (`청구항 1 [구성 1-2]`)
    text: str


@dataclass(frozen=True)
class Effects:
    """효과 후보 글 목록과, 원문 대조에 떨어져 뺀 문장 수."""

    lines: list[str]
    dropped: int = 0


def _candidates(differences: list[Difference], index: SpecIndex, k: int) -> dict[str, SpecChunk]:
    """차이점 글자를 질의로 출원서 BM25 상위 k 조각을 모은다 (조각마다 한 번만)."""
    found: dict[str, SpecChunk] = {}
    if index.searcher is None:
        return found
    by_id = {c.chunk.chunk_id: c for c in index.chunks}
    for d in differences:
        for hit in index.searcher.search(d.text, "cite", "bm25", k).hits:
            found[hit.chunk_id] = by_id[hit.chunk_id]
    return found


def _locate(quote: str, chunks: list[SpecChunk], min_chars: int) -> tuple[SpecChunk, str] | None:
    """명세서 전체에서 문장을 찾는다. (문장이 시작하는 조각, 그 조각에서 그대로 자른 글자).

    한 조각 안에 없으면, 쪽이 바뀌어 같은 문단이 다음 조각으로 이어진 곳(앞 조각 끝 + 뒤 조각 앞)도
    본다.
    너무 짧은 글자는 아무 데나 맞으므로 받지 않는다.
    """
    for c in chunks:
        span = find_span(quote, c.chunk.text)
        if span is not None and not is_too_short(quote, c.chunk.text, min_chars):
            return c, c.chunk.text[span[0] : span[1]]
    for a, b in zip(chunks, chunks[1:], strict=False):
        joined = f"{a.chunk.text}\n{b.chunk.text}"
        span = find_span(quote, joined)
        # 앞 조각 안에서 시작해 뒤 조각으로 걸친 문장만 (뒤 조각 안은 위에서 이미 봄)
        if span is not None and span[0] < len(a.chunk.text) < span[1]:
            if not is_too_short(quote, joined, min_chars):
                return a, joined[span[0] : span[1]]
    return None


def _check(
    answer: EffectAnswer,
    differences: list[Difference],
    candidates: dict[str, SpecChunk],
    chunks: list[SpecChunk],
    min_chars: int,
) -> tuple[Effects, list[str]]:
    """(효과 후보, 검사 오류). 원문에서 못 찾은 문장은 후보에 넣지 않고 건수만 센다."""
    by_no = {d.no: d for d in differences}
    lines: list[str] = []
    errors: list[str] = []
    dropped = 0
    for i, pick in enumerate(answer.effects):
        d = by_no.get(pick.difference_no)
        if d is None:
            errors.append(f"effects[{i}]: 없는 차이점 번호 {pick.difference_no}")
            dropped += 1
            continue
        chosen = candidates.get(pick.chunk_id)
        found = None
        if chosen is not None:
            found = _locate(pick.quote, [chosen], min_chars)
        if found is None:
            # 모델이 고른 조각에 없다: 명세서 전체에서 한 번 더 찾는다
            errors.append(f"effects[{i}]: quote가 고른 조각 {pick.chunk_id!r} 글에 그대로 없음")
            found = _locate(pick.quote, chunks, min_chars)
            if found is not None:
                errors.pop()  # 다른 곳에서 찾았으니 모델을 다시 부를 일은 아니다
        if found is None:
            dropped += 1
            continue
        chunk, text = found
        text = " ".join(text.split())  # 쪽을 넘은 줄바꿈은 한 칸으로
        lines.append(f"{chunk.chunk.location.label} {text} (관련 차이점: {d.location})")
    return Effects(list(dict.fromkeys(lines)), dropped), errors


def extract_effects(
    differences: list[Difference], index: SpecIndex, config: F3Config, *, ctx: RunContext, who: str
) -> Effects:
    """차이점마다 명세서 효과 문장 후보를 뽑는다 (못 뽑으면 빈 목록).

    호출 실패(형식 두 번 틀림·전송 오류·상한)는 삼키지 않고 올린다: 부르는 쪽이 정한다.
    """
    candidates = _candidates(differences, index, config.settings.effect_search.k)
    if not candidates:
        logger.warning("%s: 명세서 후보 조각이 0개라 효과 후보를 뽑지 않음", who)
        return Effects([])
    shown = [{"chunk_id": cid, "text": c.chunk.text} for cid, c in sorted(candidates.items())]
    variables = {
        "differences": json.dumps(
            [{"no": d.no, "location": d.location, "text": d.text} for d in differences],
            ensure_ascii=False,
            indent=1,
        ),
        "spec_chunks": json.dumps(shown, ensure_ascii=False, indent=1),
        "retry_note": "",
    }
    min_chars = config.settings.min_quote_chars

    def check(answer: EffectAnswer):
        return _check(answer, differences, candidates, index.chunks, min_chars)

    return call_checked(STEP, variables, EffectAnswer, check, ctx=ctx, who=who)
