"""정답 파일 읽기 (design.md 7-1 정답 파일). 한 줄 = 정답 줄 하나."""

import json
import re
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

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
    # 법령 항목의 정답 판본. 한 줄에 다른 법령(특허법 조문, 심사기준 쪽)이 같이 오면
    # 판본이 서로 다르므로 줄이 아니라 항목마다 둔다. 인용문헌 항목은 null
    gold_edition: Edition | None = None


# 정답 줄 ID 꼴 (design 7-1). 발송번호 + 거절이유 순번 (+ 청구항 + 공보 번호)
# 발송번호에는 ':'가 없다. 이 꼴이면 CQ 모으기에서 같은 줄을 같은 ID로 맞출 수 있다
_ROW_ID = {
    "law": re.compile(r"^[^:\s]+:r[1-9][0-9]*$"),
    "cite": re.compile(r"^[^:\s]+:r[1-9][0-9]*:c[1-9][0-9]*:[^:\s]+$"),
}


class GoldRow(BaseModel):
    """정답 줄 하나: 질의 + 정답 항목들."""

    model_config = ConfigDict(extra="forbid")

    row_id: str
    corpus: Corpus
    query: str
    doc_ids: list[str] | None = None
    as_of: date | None = None
    items: list[GoldItem]
    exclude: str | None = None  # null / no_location / clarity / same_as_other

    @model_validator(mode="after")
    def _check_row(self) -> GoldRow:
        # 메시지에 질의 글자는 넣지 않는다 (row_id만)
        if not _ROW_ID[self.corpus].match(self.row_id):
            form = (
                "<발송번호>:r<거절이유 순번>"
                if self.corpus == "law"
                else "<발송번호>:r<거절이유 순번>:c<청구항>:<공보 번호>"
            )
            raise ValueError(f"row_id {self.row_id!r}이 {self.corpus} 꼴 {form}이 아니다")
        if self.corpus == "cite":
            pub = self.row_id.rsplit(":", 1)[1]
            if self.doc_ids is not None and pub not in self.doc_ids:
                raise ValueError(f"row_id {self.row_id!r}의 공보 번호가 doc_ids에 없다")
            if any(item.gold_edition is not None for item in self.items):
                raise ValueError(f"row_id {self.row_id!r}: 인용문헌 항목에는 gold_edition이 없다")
        return self

    def edition_confirmed(self) -> bool:
        """법령 줄: 모든 항목의 정답 판본이 확인됨이어야 채점한다 (하나라도 모르면 줄을 뺌)."""
        return all(
            item.gold_edition is not None
            and item.gold_edition.status == "confirmed"
            and item.gold_edition.effective_from is not None
            for item in self.items
        )


def _row_rule_reason(e: Exception) -> str:
    if not isinstance(e, ValidationError):
        return ""
    msgs = [
        str(err.get("ctx", {}).get("error", ""))
        for err in e.errors()
        if err.get("type") == "value_error"
    ]
    return (": " + "; ".join(m for m in msgs if m)) if any(msgs) else ""


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
            # 꼴 검사(row_id 등)에서 걸리면 그 이유도 알린다. 이유에는 row_id만 들어 있다
            why = _row_rule_reason(e)
            raise RetrievalEvalError(
                f"정답 파일 {no}번째 줄을 읽을 수 없다 ({type(e).__name__}{why})"
            ) from None
    if not rows:
        raise RetrievalEvalError(f"정답 파일이 0줄이다: {p.name}")
    return rows
