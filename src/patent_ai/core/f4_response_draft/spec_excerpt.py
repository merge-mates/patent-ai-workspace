"""보정 프롬프트에 넣을 최초 명세서 발췌: 질의와 겹치는 문단만 메모리 BM25 상위 N개로 고른다.

질의 = 그 묶음의 차이점 구성요소 글자 + 대상 청구항 글자. 모델 호출 없음, 새 패키지 없음
(retrieval의 bm25s·토크나이저를 그대로 쓴다. core → retrieval 방향은 허용: core/CLAUDE.md).
발췌는 프롬프트에만 쓴다. 근거 위치 대조는 이 모듈을 거치지 않고 원문 전체로 한다.
"""

import logging
import re

import bm25s

from patent_ai.core.llm.config import REPO_ROOT
from patent_ai.core.llm.errors import ModelConfigError
from patent_ai.core.schemas.document import PageText
from patent_ai.retrieval.tokenizer import make_tokenizer

logger = logging.getLogger(__name__)

# 문단 경계: 빈 줄, 또는 줄 맨 앞의 문단 번호([0005] · 【0005】)
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n|\n(?=\s*[\[【]\d{4}[\]】])")
# 발췌 앞에 붙이는 안내 문구 (프롬프트라 파일로 둔다)
EXCERPT_NOTE_PROMPT = "prompts/f4/amendment_spec_excerpt_note.md"
# 명세서 쪽 글자 끝의 청구범위 덩어리. 청구항 글자는 질의에 이미 들어 있어 후보 문단에서 뺀다
_CLAIMS_BLOCK = re.compile(r"【청구범위】|【청구항\s*\d+】")

_tokenizer = None


def _tokenize(text: str) -> list[str]:
    global _tokenizer
    if _tokenizer is None:  # kiwi 모델을 한 번만 올린다
        _tokenizer = make_tokenizer("kiwi")
    return _tokenizer.tokenize(text)


def _excerpt_note() -> str:
    path = REPO_ROOT / EXCERPT_NOTE_PROMPT
    if not path.is_file():
        raise ModelConfigError(f"명세서 발췌 안내 문구 파일이 없음: {path}")
    note = path.read_text(encoding="utf-8").strip()
    if not note:
        raise ModelConfigError(f"명세서 발췌 안내 문구 파일이 비어 있음: {path}")
    return note


def _excerpt_note() -> str:
    path = REPO_ROOT / EXCERPT_NOTE_PROMPT
    if not path.is_file():
        raise ModelConfigError(f"명세서 발췌 안내 문구 파일이 없음: {path}")
    note = path.read_text(encoding="utf-8").strip()
    if not note:
        raise ModelConfigError(f"명세서 발췌 안내 문구 파일이 비어 있음: {path}")
    return note


def split_paragraphs(spec: PageText) -> list[tuple[int, str]]:
    """명세서를 (쪽 번호, 문단 글자) 목록으로 나눈다. 원래 순서, 빈 문단은 뺀다."""
    out: list[tuple[int, str]] = []
    for page in spec.pages:
        for part in _PARAGRAPH_BREAK.split(page.text):
            if part.strip():
                out.append((page.page, part.strip()))
    return out


def full_spec_text(spec: PageText) -> str:
    """쪽 글자 전체 (발췌를 끈 기본 방식)."""
    return "\n\n".join(f"[쪽 {p.page}]\n{p.text}" for p in spec.pages)


def excerpt_spec_text(spec: PageText, query: str, *, top_n: int, unit_id: str) -> str:
    """질의와 점수가 높은 문단 top_n개를 원래 순서로, `[쪽 N]` 표시를 붙여 돌려준다.

    질의가 비었거나 문단이 top_n개 이하이거나 점수가 0이 아닌 문단이 없으면 전체를 돌려준다.
    """
    # 청구범위 덩어리는 발췌 자리를 차지할 뿐이라 후보에서 뺀다 (전체를 넣을 땐 그대로 나간다)
    paragraphs = [(pg, t) for pg, t in split_paragraphs(spec) if not _CLAIMS_BLOCK.search(t)]
    note = _excerpt_note()  # 파일 문제는 전체로 돌아가기 전에 먼저 멈춘다
    if len(paragraphs) <= top_n:
        logger.warning(
            "f4.amendment %s: 명세서 문단 %d개 <= top_n %d라 전체를 넣음",
            unit_id,
            len(paragraphs),
            top_n,
        )
        return full_spec_text(spec)
    q_tokens = _tokenize(query)
    if not q_tokens:
        logger.warning("f4.amendment %s: 발췌 질의가 비어 명세서 전체를 넣음", unit_id)
        return full_spec_text(spec)
    doc_tokens = [_tokenize(text) for _, text in paragraphs]
    if not any(doc_tokens):
        logger.warning("f4.amendment %s: 명세서 문단에서 낱말이 안 나와 전체를 넣음", unit_id)
        return full_spec_text(spec)
    retriever = bm25s.BM25(method="lucene", k1=1.5, b=0.75)
    retriever.index(doc_tokens, show_progress=False)
    scores = [float(s) for s in retriever.get_scores(q_tokens)]
    # 점수 내림차순, 같으면 앞 문단 먼저. 0점은 질의와 안 겹치니 뺀다
    ranked = sorted((i for i, s in enumerate(scores) if s > 0), key=lambda i: (-scores[i], i))
    if not ranked:
        logger.warning("f4.amendment %s: 질의와 겹치는 문단이 없어 명세서 전체를 넣음", unit_id)
        return full_spec_text(spec)
    keep = sorted(ranked[:top_n])  # 고른 뒤에는 원래 순서로
    logger.info(
        "f4.amendment %s: 명세서 문단 %d개 중 %d개만 넣음", unit_id, len(paragraphs), len(keep)
    )
    # 같은 쪽 문단은 한 `[쪽 N]` 아래로 모은다
    blocks: list[tuple[int, list[str]]] = []
    for i in keep:
        page, text = paragraphs[i]
        if blocks and blocks[-1][0] == page:
            blocks[-1][1].append(text)
        else:
            blocks.append((page, [text]))
    body = "\n\n".join(f"[쪽 {page}]\n" + "\n".join(texts) for page, texts in blocks)
    return f"{note}\n\n{body}"
