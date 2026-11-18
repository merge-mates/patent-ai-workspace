"""검색 채점기 (design.md 2절 흐름, 7-1 채점기, 7-3 계산식).

명령: uv run python -m eval.retrieval.score --config experiments/<실험>/config.yaml
흐름: 정답 읽기 -> 실행 전 검사 -> 뺄 줄 -> 줄마다 search -> 맞음 판정 -> 계산 -> scores.json.
CQ 후보 파일은 main이 write_cq로 쓴다 (cq.py).
"""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from eval.retrieval.checks import REPO_ROOT, gold_path, preflight
from eval.retrieval.config import RetrievalEvalConfig, load_config
from eval.retrieval.cq import write_cq
from eval.retrieval.errors import RetrievalEvalError
from eval.retrieval.gold import GoldRow, load_gold
from eval.retrieval.matchers import MATCHERS, LawMatcher, Matcher
from eval.retrieval.metrics import random_hit, random_recall, row_hit, row_recall
from patent_ai.retrieval import get_searcher
from patent_ai.retrieval.repository import ChunkRepository, InMemoryChunkRepository

METRIC_NAME = "심사관 지정 위치 회수율"
# scores.json failures에 쓰는 이름 (정해진 것만)
FAILURE_KEYS = [
    "excluded_no_location",
    "excluded_clarity",
    "excluded_same_as_other",
    "excluded_text_missing",
    "excluded_edition_unverified",
    "cq_candidates",
    "recall_ratio_undefined",
]
EXCLUDE_TO_KEY = {
    "no_location": "excluded_no_location",
    "clarity": "excluded_clarity",
    "same_as_other": "excluded_same_as_other",
}


@dataclass
class RowResult:
    """점수에 들어간 줄 하나의 결과. scores.json에는 싣지 않는다 (task-5 CQ가 쓴다)."""

    row: GoldRow
    found_by_rank: list[set[int]]  # 순위마다 그 조각이 맞힌 항목 번호
    hits: list  # 순위 순 SearchHit
    n_scope: int  # 검색 범위 조각 수 N
    match_sizes: list[int]  # 항목마다 범위 안에서 맞는 조각 수 Mi
    union_size: int  # 어느 항목에든 맞는 조각 수


@dataclass
class ScoreReport:
    scores: dict  # scores.json 내용
    rows: list[RowResult] = field(default_factory=list)
    k_max: int = 0  # 검색에 쓴 가장 큰 k (CQ 파일의 k)


def _check_experiment(experiment: str) -> None:
    # 실험 이름이 경로 조각이면 폴더 밖으로 나갈 수 있다
    if not experiment or "/" in experiment or "\\" in experiment or ".." in experiment:
        raise RetrievalEvalError("실험 이름에 경로 조각(/, .. 등)이 있다")


def default_scores_dir(experiment: str, chunks_mode: bool) -> Path:
    """--chunks(가짜 조각)이면 work/ 아래, 진짜 저장소면 experiments/ 아래."""
    _check_experiment(experiment)
    if chunks_mode:
        return REPO_ROOT / "work" / "retrieval" / experiment
    return REPO_ROOT / "experiments" / experiment


def default_cq_dir(experiment: str) -> Path:
    _check_experiment(experiment)
    return REPO_ROOT / "work" / "retrieval" / experiment


def _git_commit() -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return r.stdout.strip() or "unknown"
    except subprocess.CalledProcessError, OSError:
        return "unknown"


def _matcher_for(cfg: RetrievalEvalConfig) -> Matcher:
    if cfg.corpus == "law":
        return LawMatcher(cfg.law_location_rule)
    return MATCHERS[cfg.corpus]


def score(
    cfg: RetrievalEvalConfig,
    repo: ChunkRepository,
    goldsets_root: Path,
    commit: str,
    *,
    chunks_mode: bool = True,
    scores_dir: Path | None = None,
    cq_dir: Path | None = None,
) -> ScoreReport:
    """정답 줄마다 검색해 점수를 낸다. 파일은 쓰지 않는다 (쓰기는 main).

    돌려준 scores의 failures.cq_candidates는 0이다. 실제 건수는 main이 write_cq 뒤에 채운다.
    Postgres 저장소로 돌릴 때(m2-i2)는 chunks_mode=False를 넘겨야 기본 출력이 experiments/로 간다.
    """
    started = time.monotonic()
    goldsets_root = Path(goldsets_root)
    path = gold_path(cfg, goldsets_root)
    gold = load_gold(path)
    preflight(
        cfg,
        gold,
        repo,
        goldsets_root,
        chunks_mode=chunks_mode,
        scores_dir=scores_dir or default_scores_dir(cfg.experiment, chunks_mode),
        cq_dir=cq_dir or default_cq_dir(cfg.experiment),
    )

    matcher = _matcher_for(cfg)
    failures = dict.fromkeys(FAILURE_KEYS, 0)
    # 색인 판은 설정의 값이 기준이다 (settings에 따로 없어도 넣어 준다)
    searcher = get_searcher(cfg.impl, repo, {**cfg.settings, "index_version": cfg.index_version})
    k_max = max(cfg.k)
    results: list[RowResult] = []

    for row in gold:
        # 3. 검색 전에 뺄 줄
        if row.exclude is not None:
            key = EXCLUDE_TO_KEY.get(row.exclude)
            if key is None:
                raise RetrievalEvalError(f"줄 {row.row_id}: 모르는 exclude 값")
            failures[key] += 1
            continue
        if cfg.corpus == "law" and (
            row.gold_edition is None or row.gold_edition.status != "confirmed"
        ):
            failures["excluded_edition_unverified"] += 1
            continue
        if not row.items:
            # 항목이 없으면 맞힐 것이 없다 (load 단계에서 막혀야 하지만 한 번 더 본다)
            failures["excluded_no_location"] += 1
            continue

        # 4. 줄마다 search를 한 번 (k는 가장 큰 값, 작은 k는 앞부분을 자른다)
        try:
            result = searcher.search(
                row.query, cfg.corpus, cfg.mode, k_max, doc_ids=row.doc_ids, as_of=row.as_of
            )
        except Exception as e:  # 줄 하나의 검색 예외는 조용히 넘기지 않는다
            # 메시지에 질의 글자가 섞일 수 있어 예외 종류만 적는다
            raise RetrievalEvalError(f"줄 {row.row_id}: 검색 실패 ({type(e).__name__})") from None
        if result.status == "unverified":  # 본문 미확보는 여기서만 정한다
            failures["excluded_text_missing"] += 1
            continue
        # 채점기가 색인 판을 한 번 더 본다
        if any(h.index_version != cfg.index_version for h in result.hits):
            raise RetrievalEvalError(f"줄 {row.row_id}: 결과에 다른 색인 판 조각이 섞였다")

        # 7. 검색 범위 N과 항목별 맞는 조각 수 Mi
        scope = repo.chunks(cfg.corpus, cfg.index_version, row.doc_ids, row.as_of)
        if not scope:
            raise RetrievalEvalError(f"줄 {row.row_id}: 검색 범위 조각이 0개다")
        results.append(
            RowResult(
                row=row,
                found_by_rank=[
                    {i for i, item in enumerate(row.items) if matcher.matches(h, item, row)}
                    for h in result.hits
                ],
                hits=list(result.hits),
                n_scope=len(scope),
                match_sizes=[
                    sum(1 for c in scope if matcher.matches(c, item, row)) for item in row.items
                ],
                union_size=sum(
                    1 for c in scope if any(matcher.matches(c, item, row) for item in row.items)
                ),
            )
        )

    # 5. 남은 줄이 0개면 빈 평균으로 성공하지 않는다
    if not results:
        raise RetrievalEvalError("점수에 넣을 줄이 0개다 (모두 제외됨)")

    metrics: dict[str, float] = {}
    n = len(results)
    for k in sorted(set(cfg.k)):
        hit = sum(row_hit(r.found_by_rank, k) for r in results) / n
        rec = sum(row_recall(r.found_by_rank, len(r.row.items), k) for r in results) / n
        rand_rec = sum(random_recall(r.n_scope, r.match_sizes, k) for r in results) / n
        rand_hit = sum(random_hit(r.n_scope, r.union_size, k) for r in results) / n
        metrics[f"hit@{k}"] = hit
        metrics[f"recall@{k}"] = rec
        metrics[f"random_hit@{k}"] = rand_hit
        metrics[f"random_recall@{k}"] = rand_rec
        if rand_rec > 0:
            metrics[f"recall_ratio@{k}"] = rec / rand_rec
        else:
            # 분모가 0이면 배수를 만들 수 없다: 키를 빼고 건수만 센다
            failures["recall_ratio_undefined"] += 1

    scores = {
        "experiment": cfg.experiment,
        "commit": commit,
        "goldset": cfg.goldset,
        "goldset_version": cfg.goldset_version,
        "gold_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "corpus": cfg.corpus,
        "index_version": cfg.index_version,
        "mode": cfg.mode,
        "impl": cfg.impl,
        "metric_name": METRIC_NAME,
        "n": n,
        "metrics": metrics,
        "failures": failures,
        "cost": {  # 모델 호출이 없어 seconds만 채운다
            "usd": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "external_calls": 0,
            "seconds": round(time.monotonic() - started, 3),
        },
    }
    return ScoreReport(scores=scores, rows=results, k_max=k_max)


def main(argv: list[str] | None = None, commit: str | None = None) -> int:
    ap = argparse.ArgumentParser(prog="eval.retrieval.score")
    ap.add_argument("--config", required=True)
    ap.add_argument("--goldsets-root", default="data/goldsets")
    ap.add_argument("--chunks", default=None, help="조각 JSONL. 없으면 Postgres")
    ap.add_argument("--scores-dir", default=None)
    ap.add_argument("--cq-dir", default=None)
    args = ap.parse_args(argv)

    if args.chunks is None:
        # m2-i2가 PostgresChunkRepository를 만든 뒤 여기 한 줄로 잇는다
        print("Postgres 저장소 없음(m2-i2). --chunks <조각 jsonl>을 주세요", file=sys.stderr)
        return 1
    try:
        cfg = load_config(args.config)
        repo = InMemoryChunkRepository.from_jsonl(cfg.corpus, args.chunks)
        scores_dir = (
            Path(args.scores_dir)
            if args.scores_dir
            else default_scores_dir(cfg.experiment, chunks_mode=True)
        )
        cq_dir = Path(args.cq_dir) if args.cq_dir else default_cq_dir(cfg.experiment)
        report = score(
            cfg,
            repo,
            Path(args.goldsets_root),
            commit if commit is not None else _git_commit(),
            chunks_mode=True,
            scores_dir=scores_dir,
            cq_dir=cq_dir,
        )
    except RetrievalEvalError as e:
        print(f"채점 실패: {e}", file=sys.stderr)
        return 1
    except (ValueError, OSError) as e:
        # 조각 파일 문제 등. 조각 글자가 섞일 수 있어 종류만 적는다
        print(f"채점 실패: {type(e).__name__}", file=sys.stderr)
        return 1

    # CQ 후보 파일은 git 밖 폴더에 쓰고, 건수만 scores.json에 남긴다
    report.scores["failures"]["cq_candidates"] = write_cq(report, cq_dir / "cq_candidates.jsonl")
    scores_dir.mkdir(parents=True, exist_ok=True)
    (scores_dir / "scores.json").write_text(
        json.dumps(report.scores, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"scores.json 저장: n={report.scores['n']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
