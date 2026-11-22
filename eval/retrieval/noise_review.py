"""노이즈 상위 오답 확인표 만들기 (이슈 #178 T4).

둘째 점수(노이즈 범위)에서 상위 k에 정답 위치가 없던 줄은 채점기가 CQ 후보 파일
(`work/retrieval/<실험>/cq_candidates.jsonl`)에 상위 조각과 함께 남긴다. 이 명령은 그중
노이즈 문헌(정답 문헌이 아닌 것) 조각이 상위 k에 든 줄마다 **가장 위 노이즈 조각 하나**를 골라
사람(또는 판정자)이 "그 조각이 청구항 구성요소를 실제로 보여 주나"를 적을 표(CSV)를 만든다.

- 노이즈 종류: 풀 표에서 `only_oas`가 있으면 C(같은 IPC·비슷한 낱말 공보), 없으면 B(tune 인용문헌).
  B는 정답 파일에서 그 OA가 인용한 문헌이면 "같은 OA", 아니면 "다른 OA" (같은 OA 인용문헌은
  심사관이 그 사건에 인용한 문헌이라 관련이 나오기 쉽다, #256 리뷰).
- 표에는 질의·조각 원문이 들어가므로 git 밖 경로에만 쓴다
  (출원번호는 없지만 발송번호가 줄 ID에 있다).

실행: uv run python -m eval.retrieval.noise_review
        --cq work/retrieval/m2-i3-cite-search-hybrid-noise-c/cq_candidates.jsonl
        --chunks data/processed/cite_search/cite-idx-v4.jsonl
        --pool data/goldsets/tune/retrieval/cite_pool_bc.yaml
        --gold data/goldsets/tune/retrieval/cite_gold.jsonl
        --out work/t4_review/hybrid_c_top_noise.csv
"""

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from patent_ai.git_paths import is_git_ignored as git_ignored_strict  # 저장소 밖도 거절

TEXT_MAX = 400  # 표 칸 하나에 넣는 글 길이 (사람이 훑기 쉽게)
COLUMNS = [
    "번호",
    "줄",
    "노이즈_순위",
    "노이즈_종류",
    "B_출처",
    "노이즈_문헌",
    "노이즈_위치",
    "상위_노이즈수",
    "질의(청구항 구성요소)",
    "정답_위치",
    "정답_글",
    "노이즈_글",
    "판정",
    "메모",
]

# chunk_id -> (doc_id, location, text)
Chunks = dict[str, tuple[str, dict, str]]


def _flat(text: str, n: int = TEXT_MAX) -> str:
    return re.sub(r"\s+", " ", text or "").strip()[:n]


def _gold_text(doc_id: str, items: list[dict], chunks: Chunks) -> str:
    """정답 위치의 글 (문단·청구항·논문 쪽 범위면 첫 번호가 든 조각). 도면만이면 빈칸."""
    for it in items:
        kind, start = it.get("kind"), it.get("start")
        if kind not in ("paragraph", "claim", "page") or start is None:  # page = 논문 쪽
            continue
        for d, loc, text in chunks.values():
            if d != doc_id or loc.get("kind") != kind or loc.get("start") is None:
                continue
            if loc["start"] <= start <= (loc.get("end") or loc["start"]):
                return f"({loc.get('label')}) " + _flat(text, TEXT_MAX - 20)
    return ""


def build_review_rows(
    cqs: list[dict], chunks: Chunks, pool_docs: dict[str, dict], oa_docs: dict[str, set[str]]
) -> list[dict]:
    """CQ 후보 줄 → 확인표 줄 (노이즈 조각이 없는 줄은 뺀다)."""
    rows: list[dict] = []
    for c in cqs:
        oa, gold = c["row_id"].split(":")[0], c["row_id"].split(":")[-1]
        noise = [
            (rank, f)
            for rank, f in enumerate(c.get("found") or [], start=1)
            if f["chunk_id"] in chunks and chunks[f["chunk_id"]][0] != gold
        ]
        if not noise:
            continue
        rank, top = noise[0]
        doc = chunks[top["chunk_id"]][0]
        is_c = bool((pool_docs.get(doc) or {}).get("only_oas"))
        rows.append(
            {
                "번호": len(rows) + 1,
                "줄": c["row_id"],
                "노이즈_순위": rank,
                "노이즈_종류": "C" if is_c else "B",
                "B_출처": ""
                if is_c
                else ("같은 OA" if doc in oa_docs.get(oa, set()) else "다른 OA"),
                "노이즈_문헌": doc,
                "노이즈_위치": top.get("label"),
                "상위_노이즈수": len(noise),
                "질의(청구항 구성요소)": _flat(c.get("query", ""), 220),
                "정답_위치": ", ".join(str(i.get("label")) for i in c.get("items") or []),
                "정답_글": _gold_text(gold, c.get("items") or [], chunks),
                "노이즈_글": _flat(chunks[top["chunk_id"]][2]),
                "판정": "",
                "메모": "",
            }
        )
    return rows


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def main(
    argv: list[str] | None = None, ignored: Callable[[Path], bool] = git_ignored_strict
) -> int:
    ap = argparse.ArgumentParser(prog="eval.retrieval.noise_review")
    ap.add_argument("--cq", required=True, help="채점기가 남긴 cq_candidates.jsonl")
    ap.add_argument("--chunks", required=True, help="그 색인 판의 조각 JSONL")
    ap.add_argument("--pool", required=True, help="노이즈 풀 표 (C안이면 cite_pool_bc.yaml)")
    ap.add_argument("--gold", required=True, help="cite_gold.jsonl (같은 OA 인용문헌 가리기)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    out = Path(args.out).resolve()
    if not ignored(out):
        # 표에 질의·조각 원문이 들어간다: 커밋될 수 있는 곳이면 아무것도 쓰지 않는다
        print(f"--out 경로가 git 제외가 아님 (커밋될 수 있음): {out}", file=sys.stderr)
        return 1
    import yaml

    try:
        cqs = _read_jsonl(Path(args.cq))
        need = {f["chunk_id"] for c in cqs for f in c.get("found") or []}
        gold_docs = {c["row_id"].split(":")[-1] for c in cqs}
        chunks: Chunks = {}
        chunk_versions: set[str] = set()
        for line in Path(args.chunks).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            ch = json.loads(line)
            if ch.get("index_version"):
                chunk_versions.add(ch["index_version"])
            # 상위 조각과 정답 문헌 조각만 메모리에 둔다 (색인 전체는 수백 MB)
            if ch["chunk_id"] in need or ch["doc_id"] in gold_docs:
                chunks[ch["chunk_id"]] = (
                    ch["doc_id"],
                    ch.get("location") or {},
                    ch.get("text", ""),
                )
        pool_docs = (yaml.safe_load(Path(args.pool).read_text(encoding="utf-8")) or {}).get(
            "docs"
        ) or {}
        oa_docs: dict[str, set[str]] = defaultdict(set)
        for g in _read_jsonl(Path(args.gold)):
            if g.get("corpus") == "cite":
                oa_docs[g["row_id"].split(":")[0]].update(g.get("doc_ids") or [])
    except (OSError, json.JSONDecodeError, KeyError, yaml.YAMLError) as e:
        print(f"확인표 만들기 실패: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    # CQ 후보를 만든 색인 판과 조각 파일의 판이 다르면 조각 번호가 맞아도 글이 다를 수 있다
    cq_versions = {c["index_version"] for c in cqs if c.get("index_version")}
    if cq_versions and chunk_versions and not cq_versions <= chunk_versions:
        print(
            f"색인 판이 다르다: CQ 후보 {sorted(cq_versions)}, 조각 파일 {sorted(chunk_versions)}"
            " (확인표를 쓰지 않음)",
            file=sys.stderr,
        )
        return 1
    # 상위 조각이 하나라도 빠지면 "가장 위 노이즈"가 다른 조각으로 바뀐다 (#256 리뷰): 쓰지 않는다
    missing = need - chunks.keys()
    if missing:
        print(
            f"CQ 후보의 상위 조각 {len(missing)}개가 조각 파일에 없다 (확인표를 쓰지 않음)."
            " --chunks가 CQ 후보를 만든 색인 판의 파일인지 본다",
            file=sys.stderr,
        )
        return 1
    rows = build_review_rows(cqs, chunks, pool_docs, oa_docs)
    if not rows:
        print("노이즈 조각이 상위에 든 줄이 0개다 (확인표를 쓰지 않음)", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fp:  # 엑셀에서 한글이 안 깨지게 BOM
        w = csv.DictWriter(fp, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"확인표 저장: CQ {len(cqs)}줄 중 노이즈가 상위에 든 {len(rows)}줄", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
