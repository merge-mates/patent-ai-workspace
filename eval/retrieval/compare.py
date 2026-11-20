"""검색 방식 비교 표 (design.md 7-5, requirements 10).

명령: uv run python -m eval.retrieval.compare --rows bm25=<p> vector=<p> --k 10 [--out <md>]
입력은 `score --rows-out`이 쓴 줄별 JSONL (row_id, doc_ids, first_hit_rank).
방식마다 Hit@1·3·5·10을 전체 / 한국 공보 / 논문으로 나누고, CQ 수와 "이 방식만 찾은 줄" 수를 센다.
"""

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

HIT_KS = (1, 3, 5, 10)
# 묶음 이름. 앞의 셋은 늘 표에 나오고, "그 밖"은 줄이 있을 때만 나온다
GROUPS = ("전체", "한국 공보", "논문", "그 밖")


class CompareError(Exception):
    """비교 입력이 잘못됐다 (종료 1)."""


@dataclass(frozen=True)
class RowHit:
    row_id: str
    doc_ids: list[str]
    first_hit_rank: int | None  # 1부터, 못 찾으면 None


@dataclass
class CompareTable:
    k: int
    methods: list[str]
    n: dict[str, int]  # 묶음별 줄 수
    hit: dict[str, dict[str, dict[int, float | None]]]  # 방식 -> 묶음 -> k -> Hit (줄 없으면 None)
    cq: dict[str, int]  # 방식 -> 상위 k에 없는 줄 수
    only: dict[str, int]  # 방식 -> 상위 k 안에서 이 방식만 찾은 줄 수
    warnings: list[str] = field(default_factory=list)


def group_of(doc_ids: list[str]) -> str:
    """첫 doc_id 앞말로 묶음을 정한다. KR이면 한국 공보, NPL-이면 논문, 나머지는 그 밖."""
    if doc_ids and doc_ids[0].startswith("KR"):
        return "한국 공보"
    if doc_ids and doc_ids[0].startswith("NPL-"):
        return "논문"
    return "그 밖"


def _found(r: RowHit, k: int) -> bool:
    return r.first_hit_rank is not None and r.first_hit_rank <= k


def compare(rows: dict[str, list[RowHit]], k: int) -> CompareTable:
    """방식별 줄별 결과를 표 값으로 만든다. 세 방식의 row_id 집합은 같아야 한다."""
    methods = list(rows)
    if not methods:
        raise CompareError("비교할 방식이 없다")
    by_id = {m: {r.row_id: r for r in rows[m]} for m in methods}
    for m in methods:
        if len(by_id[m]) != len(rows[m]):
            raise CompareError(f"{m}: row_id가 겹친다")
    ids = set(by_id[methods[0]])
    for m in methods[1:]:
        other = set(by_id[m])
        if other != ids:
            diff = len(ids ^ other)
            raise CompareError(
                f"row_id 집합이 다르다: {methods[0]} {len(ids)}줄, {m} {len(other)}줄, "
                f"서로 다른 줄 {diff}개"
            )

    warnings: list[str] = []
    ordered = sorted(ids)
    base = by_id[methods[0]]
    members: dict[str, list[str]] = {g: [] for g in GROUPS}
    for rid in ordered:
        members["전체"].append(rid)
        members[group_of(base[rid].doc_ids)].append(rid)
    n = {g: len(v) for g, v in members.items()}
    if n["그 밖"]:
        warnings.append(f"KR·NPL-로 시작하지 않는 doc_id 줄 {n['그 밖']}개를 '그 밖'으로 센다")
    for g in ("한국 공보", "논문"):
        if n[g] == 0:
            warnings.append(f"{g} 줄이 없다 (그 칸은 '줄 없음')")

    hit: dict[str, dict[str, dict[int, float | None]]] = {}
    for m in methods:
        hit[m] = {}
        for g, rids in members.items():
            # 줄이 0개인 묶음은 0으로 나누지 않고 None (표에는 "줄 없음")
            hit[m][g] = {
                kk: (sum(_found(by_id[m][r], kk) for r in rids) / len(rids) if rids else None)
                for kk in HIT_KS
            }
    cq = {m: sum(not _found(by_id[m][r], k) for r in ordered) for m in methods}
    only = {
        m: sum(
            _found(by_id[m][r], k) and not any(_found(by_id[o][r], k) for o in methods if o != m)
            for r in ordered
        )
        for m in methods
    }
    return CompareTable(k=k, methods=methods, n=n, hit=hit, cq=cq, only=only, warnings=warnings)


def render(t: CompareTable) -> str:
    """마크다운 표. 줄 없는 묶음은 '줄 없음'."""
    out: list[str] = []
    for g in GROUPS:
        if g == "그 밖" and t.n[g] == 0:
            continue
        out.append(f"### {g} (줄 {t.n[g]}개)")
        out.append("| 방식 | " + " | ".join(f"Hit@{kk}" for kk in HIT_KS) + " |")
        out.append("|---|" + "---|" * len(HIT_KS))
        for m in t.methods:
            cells = [
                "줄 없음" if t.hit[m][g][kk] is None else f"{t.hit[m][g][kk]:.3f}" for kk in HIT_KS
            ]
            out.append(f"| {m} | " + " | ".join(cells) + " |")
        out.append("")
    out.append(f"### CQ와 한 방식만 찾은 줄 (상위 {t.k} 기준)")
    out.append(f"| 방식 | CQ (상위 {t.k}에 없음) | 이 방식만 찾은 줄 |")
    out.append("|---|---|---|")
    for m in t.methods:
        out.append(f"| {m} | {t.cq[m]} | {t.only[m]} |")
    return "\n".join(out) + "\n"


def load_rows(path: Path) -> list[RowHit]:
    """score --rows-out 파일 읽기. 모양이 틀리면 CompareError."""
    out: list[RowHit] = []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise CompareError(f"{path}: 못 읽음 ({type(e).__name__})") from None
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            out.append(RowHit(d["row_id"], list(d["doc_ids"]), d["first_hit_rank"]))
        except ValueError, KeyError, TypeError:
            raise CompareError(f"{path}: {i}번째 줄 모양이 틀림") from None
    if not out:
        raise CompareError(f"{path}: 줄이 0개")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="eval.retrieval.compare")
    ap.add_argument("--rows", nargs="+", required=True, help="이름=경로 (방식마다)")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--out", default=None, help="마크다운 저장 경로")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    try:
        if args.k < 1:
            raise CompareError("--k는 1 이상")
        paths: dict[str, Path] = {}
        for spec in args.rows:
            name, sep, p = spec.partition("=")
            if not sep or not name or not p:
                raise CompareError(f"--rows 값이 이름=경로 꼴이 아니다: {spec}")
            if name in paths:
                raise CompareError(f"방식 이름이 겹친다: {name}")
            paths[name] = Path(p)
        if len(paths) < 2:
            raise CompareError("방식이 둘 이상 필요하다")
        table = compare({m: load_rows(p) for m, p in paths.items()}, args.k)
    except CompareError as e:
        print(f"비교 실패: {e}", file=sys.stderr)
        return 1
    for w in table.warnings:
        logger.warning(w)
    text = render(table)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
