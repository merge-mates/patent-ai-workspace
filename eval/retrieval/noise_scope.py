"""노이즈 검색 범위 만들기 (이슈 #178, 둘째 점수).

주 점수는 정답 줄마다 그 인용문헌 하나 안에서 찾는다 (search-gold.md 규칙 1).
둘째 점수는 다른 문헌(노이즈)을 섞은 범위에서 찾는다. 이 모듈은 줄마다 그 범위(doc_id 목록)를
정해 git 밖 파일로 쓴다. 정답 파일(cite_gold.jsonl)은 바꾸지 않는다 (주 점수·VERSION 그대로).

B안: 풀 = 풀 표(docs)에 적은 문헌 전체 (tune 인용문헌, 같은 OA의 다른 인용문헌 포함).
C안: OA마다 같은 IPC·비슷한 낱말로 고른 공보. 풀 표에서 `only_oas`를 단 문헌으로,
     그 OA의 줄에만 넣는다 (11/21 은진 결정: 줄마다 노이즈 수가 비슷하게 맞도록).
     넣는 조건은 B안과 같다.
넣는 조건 (이슈 #178):
- 그 출원의 우선일 **전**에 공개된 것만 (당일 공개는 뺌)
- 그 출원 자신의 공보, 정답 인용문헌과 같은 특허(같은 출원번호)의 다른 공보, 비특허 문헌은 뺀다
- 정답 문헌은 조건과 상관없이 늘 넣는다 (맞힐 것이 범위에 있어야 하므로)

실행: uv run python -m eval.retrieval.noise_scope
      (기본 --gold retrieval/cite_gold.jsonl --pool retrieval/cite_pool.yaml
       --out retrieval/cite_noise_b.jsonl, 모두 <goldsets_root>/tune/ 기준)
메시지에는 row_id·발송번호·doc_id·건수만 쓴다 (질의 글자 금지).
"""

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from eval.common.errors import EvalError
from eval.common.goldset import gold_path
from eval.retrieval.errors import RetrievalEvalError
from eval.retrieval.gold import GoldRow, load_gold

log = logging.getLogger(__name__)

NPL_PREFIX = "NPL-"  # 비특허 문헌 doc_id 앞머리 (cite_gold.yaml)
EXCLUDE_REASONS = ["after_priority", "own_application", "same_patent", "npl"]


class PoolDoc(BaseModel):
    """풀 문헌 하나. date = 그 공보가 공개(등록공보는 공고)된 날."""

    model_config = ConfigDict(extra="forbid")

    app_no: str | None  # 그 공보의 출원번호 (같은 특허 가리기). 비특허는 null
    date: date
    # C안 문헌이면 넣을 OA 발송번호들. 없으면(B안) 모든 줄의 후보다
    only_oas: list[str] | None = Field(default=None, min_length=1)


class PoolOa(BaseModel):
    """정답 줄의 OA 하나 (row_id 앞의 발송번호로 찾는다)."""

    model_config = ConfigDict(extra="forbid")

    app_no: str  # 그 OA를 받은 출원의 출원번호 (자기 공보 빼기)
    priority_date: date  # 우선일 (우선권 주장이 없으면 출원일)


class PoolTable(BaseModel):
    """풀 표 (git 밖 <goldsets_root>/tune/retrieval/cite_pool.yaml)."""

    model_config = ConfigDict(extra="forbid")

    docs: dict[str, PoolDoc] = Field(min_length=1)
    oas: dict[str, PoolOa]

    @model_validator(mode="after")
    def _특허는_출원번호가_있다(self) -> PoolTable:
        # 특허 공보에 출원번호가 없으면 같은 특허 공보를 못 가린다 (조용히 섞이지 않게 막음)
        missing = [d for d, v in self.docs.items() if not d.startswith(NPL_PREFIX) and not v.app_no]
        if missing:
            raise ValueError(f"특허 문헌에 app_no가 없다: {', '.join(missing)}")
        # C안 문헌의 OA가 표에 없으면 오타다. 조용히 어느 줄에도 안 들어가는 일을 막는다
        listed = {o for v in self.docs.values() for o in v.only_oas or []}
        stray = sorted(listed - set(self.oas))
        if stray:
            raise ValueError(f"only_oas의 발송번호가 oas에 없다: {', '.join(stray)}")
        return self


@dataclass
class NoiseReport:
    rows: int = 0
    excluded: dict[str, int] = field(default_factory=lambda: dict.fromkeys(EXCLUDE_REASONS, 0))
    noise_docs_per_row: list[int] = field(default_factory=list)

    def as_dict(self) -> dict:
        n = self.noise_docs_per_row
        return {
            "rows": self.rows,
            "excluded": dict(self.excluded),
            "noise_docs_min": min(n, default=0),
            "noise_docs_max": max(n, default=0),
        }


def _oa_no(row_id: str) -> str:
    return row_id.split(":", 1)[0]


def _skip_reason(doc_id: str, doc: PoolDoc, oa: PoolOa, gold_apps: set[str]) -> str | None:
    """노이즈로 넣지 않을 이유. 넣으면 None."""
    if doc_id.startswith(NPL_PREFIX):
        return "npl"
    if doc.app_no == oa.app_no:
        return "own_application"
    if doc.app_no in gold_apps:
        return "same_patent"
    if doc.date >= oa.priority_date:
        return "after_priority"
    return None


def build_noise_scope(
    rows: list[GoldRow], table: PoolTable
) -> tuple[dict[str, list[str]], NoiseReport]:
    """정답 줄마다 검색 범위 doc_id 목록 (정답 문헌 먼저, 그다음 노이즈 doc_id 순)."""
    rep = NoiseReport()
    out: dict[str, list[str]] = {}
    for r in rows:
        oa = table.oas.get(_oa_no(r.row_id))
        if oa is None:
            raise RetrievalEvalError(f"풀 표 oas에 발송번호가 없다: {_oa_no(r.row_id)}")
        gold_docs = list(r.doc_ids or [])
        if not gold_docs:
            raise RetrievalEvalError(f"cite 줄에 doc_ids가 없다: {r.row_id}")
        unknown = [d for d in gold_docs if d not in table.docs]
        if unknown:
            raise RetrievalEvalError(f"풀 표 docs에 정답 문헌이 없다: {', '.join(unknown)}")
        # 비특허 정답은 출원번호가 없다. None끼리 같은 특허로 보지 않는다
        gold_apps = {a for d in gold_docs if (a := table.docs[d].app_no)}
        noise: list[str] = []
        for doc_id in sorted(table.docs):
            if doc_id in gold_docs:
                continue
            only = table.docs[doc_id].only_oas
            if only is not None and _oa_no(r.row_id) not in only:
                continue  # 다른 OA의 C안 문헌: 이 줄의 후보가 아니라 빼는 이유로 세지 않는다
            why = _skip_reason(doc_id, table.docs[doc_id], oa, gold_apps)
            if why:
                rep.excluded[why] += 1
            else:
                noise.append(doc_id)
        if not noise:
            # 노이즈가 0개면 주 점수와 같은 범위다. 실패는 아니지만 알린다
            log.warning("노이즈 문헌이 0개인 줄: %s", r.row_id)
        rep.noise_docs_per_row.append(len(noise))
        out[r.row_id] = gold_docs + noise
    rep.rows = len(out)
    return out, rep


class _NoiseLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_id: str
    scope_doc_ids: list[str] = Field(min_length=1)


def load_noise_scope(path: str | Path) -> dict[str, list[str]]:
    """범위 파일을 읽는다 (row_id -> doc_id 목록). 없거나 0줄·중복이면 RetrievalEvalError."""
    p = Path(path)
    if not p.is_file():
        raise RetrievalEvalError(f"노이즈 범위 파일이 없다: {p.name}")
    out: dict[str, list[str]] = {}
    for no, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = _NoiseLine.model_validate(json.loads(line))
        except json.JSONDecodeError, ValidationError:
            raise RetrievalEvalError(f"노이즈 범위 파일 {no}번째 줄을 읽을 수 없다") from None
        if item.row_id in out:
            raise RetrievalEvalError(f"노이즈 범위 파일에 row_id 중복: {item.row_id}")
        out[item.row_id] = item.scope_doc_ids
    if not out:
        raise RetrievalEvalError(f"노이즈 범위 파일이 0줄이다: {p.name}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="eval.retrieval.noise_scope")
    ap.add_argument("--goldsets-root", default="data/goldsets")
    ap.add_argument("--goldset", default="tune")  # report 세트에는 아직 만들지 않는다 (11/21)
    ap.add_argument("--gold", default="retrieval/cite_gold.jsonl")
    ap.add_argument("--pool", default="retrieval/cite_pool.yaml")
    ap.add_argument("--out", default="retrieval/cite_noise_b.jsonl")
    args = ap.parse_args(argv)

    import yaml  # 명령에서만 쓴다

    try:
        root = Path(args.goldsets_root)
        # 세 경로 모두 세트 폴더 안만 (`..`·절대 경로 금지, eval/common)
        gold_p, pool_p, out_p = (
            gold_path(root, args.goldset, rel) for rel in (args.gold, args.pool, args.out)
        )
        rows = [r for r in load_gold(gold_p) if r.corpus == "cite"]
        if not rows:
            raise RetrievalEvalError("cite 정답 줄이 0개다")
        if not pool_p.is_file():
            raise RetrievalEvalError(f"풀 표가 없다: {pool_p.name}")
        try:
            table = PoolTable.model_validate(yaml.safe_load(pool_p.read_text(encoding="utf-8")))
        except ValidationError as e:
            raise RetrievalEvalError(f"풀 표 꼴이 맞지 않다 ({e.error_count()}곳)") from None
        scope, rep = build_noise_scope(rows, table)
        body = "".join(
            json.dumps({"row_id": k, "scope_doc_ids": v}, ensure_ascii=False) + "\n"
            for k, v in scope.items()
        )
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(body, encoding="utf-8")
    except (EvalError, OSError, yaml.YAMLError) as e:
        print(f"노이즈 범위 만들기 실패: {e}", file=sys.stderr)
        return 1
    print(f"노이즈 범위 저장: {json.dumps(rep.as_dict(), ensure_ascii=False)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
