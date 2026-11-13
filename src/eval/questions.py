"""평가 질문 파일(data/eval/questions.jsonl) 읽기.

gold 는 조문 단위 id 목록("법령명#제N조", 청커의 chunk_id 와 같은 형식).
정답이 둘 이상이면 그중 하나만 나와도 적중으로 본다(holdout-questions.md H7).
"""
import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path("data/eval/questions.jsonl")


@dataclass(frozen=True)
class Question:
    id: str
    split: str  # "dev" | "holdout"
    law: str  # 주 정답이 속한 법령 ("특허법" | "시행령" | "시행규칙")
    question: str
    gold: tuple[str, ...]
    note: str = ""


def load_questions(path: Path = DEFAULT_PATH, split: str | None = None,
                   law: str | None = None) -> list[Question]:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        q = Question(d["id"], d["split"], d["law"], d["question"], tuple(d["gold"]), d.get("note", ""))
        if (split is None or q.split == split) and (law is None or q.law == law):
            out.append(q)
    return out


# 질문 파일은 "시행령#제5조"처럼 짧은 법령 이름을 쓰고, 청커의 chunk_id 는 "특허법 시행령#제5조"처럼 전체 이름을 쓴다.
# 홀드아웃 질문 파일은 수정하지 않으므로, 코퍼스와 맞출 때는 이 별칭 표로 바꾼다.
CORPUS_LAW_NAME = {"시행령": "특허법 시행령", "시행규칙": "특허법 시행규칙"}


def corpus_law(law: str) -> str:
    return CORPUS_LAW_NAME.get(law, law)


def corpus_gold(gold: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """정답 id 의 법령 이름 부분을 코퍼스(chunk_id) 형식으로 바꾼다. 이미 코퍼스 형식이면 그대로."""
    out = []
    for g in gold:
        law, sep, rest = g.partition("#")
        out.append(f"{corpus_law(law)}{sep}{rest}")
    return tuple(out)
