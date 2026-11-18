"""정답 파일 읽기 (design.md 7-1 정답 파일). 한 줄 = 정답 줄 하나."""

import json
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from eval.retrieval.errors import RetrievalEvalError
from patent_ai.retrieval.schemas import Corpus, Edition, LocKind


class GoldItem(BaseModel):
    """심사관이 가리킨 위치 하나. start·end는 조각의 정렬 키와 같은 인코딩이다."""

    model_config = ConfigDict(extra="forbid")

    kind: LocKind
    start: int | None = None
    end: int | None = None
    label: str
    figures: list[int] = Field(default_factory=list)
    # 인용문헌 청구항 항목(kind="claim")의 청구항 번호들
    # (design 7-4: 조각 loc_claims와 겹치면 맞음)
    claims: list[int] = Field(default_factory=list)


class GoldRow(BaseModel):
    """정답 줄 하나: 질의 + 정답 항목들."""

    model_config = ConfigDict(extra="forbid")

    row_id: str
    corpus: Corpus
    query: str
    doc_ids: list[str] | None = None
    as_of: date | None = None
    gold_edition: Edition | None = None
    items: list[GoldItem]
    exclude: str | None = None  # null / no_location / clarity / same_as_other


def load_gold(path: str | Path) -> list[GoldRow]:
    """정답 파일을 읽는다. 없거나 0줄이면 RetrievalEvalError (빈 입력으로 성공하지 않음)."""
    p = Path(path)
    if not p.is_file():
        raise RetrievalEvalError(f"정답 파일이 없다: {p.name}")
    rows: list[GoldRow] = []
    for no, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(GoldRow.model_validate(json.loads(line)))
        except (json.JSONDecodeError, ValidationError) as e:
            # 원인 글자(질의 원문이 섞일 수 있음)는 찍지 않고 줄 번호만
            raise RetrievalEvalError(
                f"정답 파일 {no}번째 줄을 읽을 수 없다 ({type(e).__name__})"
            ) from None
    if not rows:
        raise RetrievalEvalError(f"정답 파일이 0줄이다: {p.name}")
    return rows
