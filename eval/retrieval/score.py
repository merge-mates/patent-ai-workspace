"""검색 채점기 (design.md 2절 흐름, 7-1 채점기, 7-3 계산식).

명령: uv run python -m eval.retrieval.score --config experiments/<실험>/config.yaml
흐름: 정답 읽기 -> 실행 전 검사 -> 뺄 줄 -> 줄마다 search -> 맞음 판정 -> 계산 -> scores.json.
CQ 후보 파일은 main이 write_cq로 쓴다 (cq.py).
"""

import argparse
import hashlib
import json
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from eval.common.goldset import gold_path as goldset_file
from eval.common.paths import check_experiment_name, git_commit
from eval.common.scores import write_scores
from eval.retrieval.checks import REPO_ROOT, gold_path, preflight
from eval.retrieval.config import RetrievalEvalConfig, load_config
from eval.retrieval.cq import write_cq
from eval.retrieval.errors import RetrievalEvalError
from eval.retrieval.gold import GoldRow, load_gold
from eval.retrieval.llm_cost import check_budget, cost_fields, invalid_attempts
from eval.retrieval.matchers import MATCHERS, LawMatcher, Matcher
from eval.retrieval.metrics import random_hit, random_recall, row_hit, row_recall
from eval.retrieval.noise_scope import load_noise_scope
from patent_ai.db.index_dump import index_fingerprint
from patent_ai.git_paths import is_git_ignored as git_ignored_strict  # 저장소 밖도 거절
from patent_ai.retrieval import get_searcher
from patent_ai.retrieval.repository import (
    ChunkRepository,
    InMemoryChunkRepository,
    PostgresChunkRepository,
)

if TYPE_CHECKING:  # 타입 표시만. 실제 import는 whole_doc_llm일 때 함수 안에서
    from patent_ai.core.llm.limits import RunContext

logger = logging.getLogger(__name__)

METRIC_NAME = "심사관 지정 위치 회수율"
# scores.json failures에 쓰는 이름 (정해진 것만)
FAILURE_KEYS = [
    "excluded_no_location",
    "excluded_clarity",
    "excluded_same_as_other",
    "excluded_body_missing",
    "excluded_edition_unverified",
    "excluded_no_edition_in_scope",
    "excluded_gold_not_in_scope",
    "excluded_gold_items_not_in_scope",
    "cq_candidates",
    "recall_ratio_undefined",
]
# 문헌 통째 LLM(whole_doc_llm)일 때만 failures에 더하는 이름
LLM_FAILURE_KEYS = ["llm_output_invalid", "not_extracted"]
WHOLE_DOC_IMPL = "whole_doc_llm"
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
    # 노이즈 범위(#178)에서만 쓴다: 순위마다 정답 문헌 조각인가, 범위 안 정답 문헌 조각 수
    gold_doc_by_rank: list[bool] = field(default_factory=list)
    gold_doc_size: int = 0
    # 결과 상태 이유. 모델 출력을 못 읽은 줄은 "not_extracted" (못 찾음과 나눠 세려는 표시)
    status_reason: str | None = None


@dataclass
class ScoreReport:
    scores: dict  # scores.json 내용
    rows: list[RowResult] = field(default_factory=list)
    k_max: int = 0  # 검색에 쓴 가장 큰 k (CQ 파일의 k)


def default_scores_dir(experiment: str, chunks_mode: bool) -> Path:
    """--chunks(가짜 조각)이면 work/ 아래, 진짜 저장소면 experiments/ 아래."""
    check_experiment_name(experiment)
    if chunks_mode:
        return REPO_ROOT / "work" / "retrieval" / experiment
    return REPO_ROOT / "experiments" / experiment


def default_cq_dir(experiment: str) -> Path:
    check_experiment_name(experiment)
    return REPO_ROOT / "work" / "retrieval" / experiment


def _matcher_for(cfg: RetrievalEvalConfig) -> Matcher:
    if cfg.corpus == "law":
        return LawMatcher(cfg.law_location_rule)
    return MATCHERS[cfg.corpus]


def new_run_context(cfg: RetrievalEvalConfig, cache_dir: Path) -> RunContext:
    """채점 실행마다 새로 만드는 모델 호출 맥락: 상한 세기·기록기는 새것, 캐시는 파일.

    테스트는 이 함수를 바꿔 끼워 가짜 전송층을 넣는다.
    """
    from patent_ai.core.llm.cache import FileCache
    from patent_ai.core.llm.limits import CallBudget, MemoryRecorder, RunContext

    return RunContext(
        run_id=cfg.experiment,
        budget=CallBudget(),
        recorder=MemoryRecorder(),
        cache=FileCache(cache_dir),
    )


def score(
    cfg: RetrievalEvalConfig,
    repo: ChunkRepository,
    goldsets_root: Path,
    commit: str,
    *,
    chunks_mode: bool = True,
    scores_dir: Path | None = None,
    cq_dir: Path | None = None,
    run_context: RunContext | None = None,
) -> ScoreReport:
    """정답 줄마다 검색해 점수를 낸다. 파일은 쓰지 않는다 (쓰기는 main).

    돌려준 scores의 failures.cq_candidates는 0이다. 실제 건수는 main이 write_cq 뒤에 채운다.
    Postgres 저장소로 돌릴 때는 chunks_mode=False를 넘겨야 기본 출력이 experiments/로 간다.
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
    settings = {**cfg.settings, "index_version": cfg.index_version}
    llm = cfg.impl == WHOLE_DOC_IMPL
    if llm:
        # 이 impl일 때만 core를 불러온다 (import하면 impl이 등록된다.
        # 다른 impl 채점은 core를 안 끌어온다)
        import patent_ai.core.cite_rank.whole_doc  # noqa: F401

        if run_context is None:
            raise RetrievalEvalError("whole_doc_llm 채점에는 run_context가 필요하다")
        settings["run_context"] = run_context
        failures.update(dict.fromkeys(LLM_FAILURE_KEYS, 0))
    searcher = get_searcher(cfg.impl, repo, settings)
    k_max = max(cfg.k)
    results: list[RowResult] = []
    # 둘째 점수(#178): 줄마다 노이즈를 섞은 검색 범위. 없으면 그 인용문헌 안(주 점수)
    noise: dict[str, list[str]] | None = None
    if cfg.noise_scope is not None:
        noise_path = goldset_file(goldsets_root, cfg.goldset, cfg.noise_scope)
        noise = load_noise_scope(noise_path)

    for row in gold:
        # 3. 검색 전에 뺄 줄
        if row.exclude is not None:
            key = EXCLUDE_TO_KEY.get(row.exclude)
            if key is None:
                raise RetrievalEvalError(f"줄 {row.row_id}: 모르는 exclude 값")
            failures[key] += 1
            continue
        if cfg.corpus == "law" and not row.edition_confirmed():
            # 항목 하나라도 정답 판본을 모르면 그 줄을 뺀다 (항목만 빼면 Recall 분모가 바뀜)
            failures["excluded_edition_unverified"] += 1
            continue
        if not row.items:
            # 항목이 없으면 맞힐 것이 없다 (load 단계에서 막혀야 하지만 한 번 더 본다)
            failures["excluded_no_location"] += 1
            continue

        search_docs = row.doc_ids
        if noise is not None:
            search_docs = noise.get(row.row_id)
            if search_docs is None:
                raise RetrievalEvalError(f"노이즈 범위 파일에 줄이 없다: {row.row_id}")
            if not set(row.doc_ids or []) <= set(search_docs):
                raise RetrievalEvalError(f"노이즈 범위에 정답 문헌이 빠졌다: {row.row_id}")
            # 노이즈 조각이 있어도 정답 문헌 본문이 없으면 맞힐 수 없다: 주 점수와 같이 뺀다
            if repo.count_chunks(cfg.corpus, cfg.index_version, row.doc_ids) == 0:
                failures["excluded_body_missing"] += 1
                continue

        if llm and cfg.budget is not None:
            # 줄을 검색하기 전에 예산을 본다: 상한에 닿았으면 반쯤 채점한 점수를 남기지 않고 멈춘다
            check_budget(
                run_context.recorder.records,
                cfg.budget.max_usd,
                cfg.budget.max_external_calls,
            )

        # 4. 줄마다 search를 한 번 (k는 가장 큰 값, 작은 k는 앞부분을 자른다)
        try:
            result = searcher.search(
                row.query, cfg.corpus, cfg.mode, k_max, doc_ids=search_docs, as_of=row.as_of
            )
        except Exception as e:  # 줄 하나의 검색 예외는 조용히 넘기지 않는다
            # 메시지에 질의 글자가 섞일 수 있어 예외 종류만 적는다
            raise RetrievalEvalError(f"줄 {row.row_id}: 검색 실패 ({type(e).__name__})") from None
        not_extracted = result.status == "unverified" and result.status_reason == "not_extracted"
        if not_extracted:
            # 모델 출력을 못 읽은 줄: 점수에서 빼지 않고 결과 0개(못 맞힌 줄)로 n에 남긴다.
            # 빼면 출력 실패가 많을수록 점수가 오른다. 건수는 failures에 따로 센다
            # 건수는 아래 results에 넣을 때 센다 (범위 밖 제외로 빠지는 줄은 두 번 세지 않게)
            pass
        elif result.status == "unverified":  # 본문 미확보는 여기서만 정한다
            failures["excluded_body_missing"] += 1
            continue
        # 채점기가 색인 판을 한 번 더 본다
        if any(h.index_version != cfg.index_version for h in result.hits):
            raise RetrievalEvalError(f"줄 {row.row_id}: 결과에 다른 색인 판 조각이 섞였다")

        # 7. 검색 범위 N과 항목별 맞는 조각 수 Mi
        scope = repo.chunks(cfg.corpus, cfg.index_version, search_docs, row.as_of)
        if not scope:
            # 기준일로 걸러 범위가 0개: 무작위 기준선을 못 정하므로
            # 이 줄만 빼고 센다 (design 2절 4번)
            failures["excluded_no_edition_in_scope"] += 1
            continue
        match_sizes = [sum(1 for c in scope if matcher.matches(c, item, row)) for item in row.items]
        # 범위 조각은 있는데 맞는 조각이 0개인 정답 항목은 검색기가 어떻게 해도 못 맞힌다 (#129).
        # 법령은 정답 판이 그날 범위에 없음(빠진 판·개정), 인용문헌은 정답 문단이 조각에 없음
        # (청킹·정답 문제). 검색 실력이 아니라 데이터 문제라 Hit·Recall·CQ에 넣지 않는다.
        # 공보 조각이 아예 없으면 위 body_missing, 범위가 0개면 위 no_edition_in_scope가 먼저 센다
        if all(m == 0 for m in match_sizes):
            # 항목이 모두 범위 밖: 줄째 뺀다. 건수만 남으면 matcher가 망가져도 소리 없이 빠지므로
            # row_id와 뺀 항목 수를 경고로 남긴다 (질의 원문은 쓰지 않음, design 2절 메시지 규칙)
            failures["excluded_gold_not_in_scope"] += 1
            logger.warning(
                "범위 안 정답 조각이 없어 줄째 뺀다: %s (항목 %d/%d)",
                row.row_id,
                len(match_sizes),
                len(match_sizes),
            )
            continue
        if 0 in match_sizes:
            # 일부만 범위 밖: 그 항목만 빼고 남은 항목으로 채점한다. 다른 항목으로 맞힌 줄까지
            # 빼면 범위 밖 정답을 막으려다 Hit가 내려간다 (11/19 인용문헌 기준선에서 9줄 중 8줄)
            failures["excluded_gold_items_not_in_scope"] += match_sizes.count(0)
            logger.warning(
                "범위 안 정답 조각이 없는 항목을 뺀다: %s (항목 %d/%d)",
                row.row_id,
                match_sizes.count(0),
                len(match_sizes),
            )
            row = row.model_copy(
                update={
                    "items": [it for it, m in zip(row.items, match_sizes, strict=True) if m > 0]
                }
            )
            match_sizes = [m for m in match_sizes if m > 0]
        if not_extracted:
            failures["not_extracted"] += 1
        results.append(
            RowResult(
                row=row,
                found_by_rank=[
                    {i for i, item in enumerate(row.items) if matcher.matches(h, item, row)}
                    for h in result.hits
                ],
                hits=list(result.hits),
                n_scope=len(scope),
                match_sizes=match_sizes,
                union_size=sum(
                    1 for c in scope if any(matcher.matches(c, item, row) for item in row.items)
                ),
                gold_doc_by_rank=[h.doc_id in (row.doc_ids or []) for h in result.hits],
                gold_doc_size=sum(1 for c in scope if c.doc_id in (row.doc_ids or [])),
                status_reason="not_extracted" if not_extracted else None,
            )
        )

    if llm and cfg.budget is not None:
        # 마지막 줄이 상한을 넘겨 쓴 경우는 줄 앞 검사가 못 본다: 끝에서 한 번 더 (점수를 안 남김)
        check_budget(
            run_context.recorder.records,
            cfg.budget.max_usd,
            cfg.budget.max_external_calls,
            final=True,
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
        if noise is not None:
            # 문헌 Hit@k: 상위 k개에 정답 문헌 조각이 하나라도 있나 (위치는 안 봄)
            metrics[f"doc_hit@{k}"] = sum(any(r.gold_doc_by_rank[:k]) for r in results) / n
            metrics[f"random_doc_hit@{k}"] = (
                sum(random_hit(r.n_scope, r.gold_doc_size, k) for r in results) / n
            )

    scores = {
        "experiment": cfg.experiment,
        "commit": commit,
        "goldset": cfg.goldset,
        "goldset_version": cfg.goldset_version,
        "gold_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "corpus": cfg.corpus,
        "index_version": cfg.index_version,
        # 색인 판 이름만 같고 내용이 다른 경우를 가린다. make index-dump 지문과 같은 계산
        # (design 5-2). 지문이 다른 실험끼리는 점수를 비교하지 않는다
        "index_fingerprint": index_fingerprint(
            c.chunk_id for c in repo.chunks(cfg.corpus, cfg.index_version, None, None)
        ),
        "mode": cfg.mode,
        "impl": cfg.impl,
        "metric_name": METRIC_NAME,
        "n": n,
        "metrics": metrics,
        "failures": failures,
        "cost": {  # 모델 호출이 없는 impl은 seconds만 채운다
            "usd": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "external_calls": 0,
            "seconds": round(time.monotonic() - started, 3),
        },
    }
    if llm:
        # 호출 기록(recorder)의 합으로 채운다. 모르는 값(None)은 0으로 메우지 않고 None으로 둔다
        records = run_context.recorder.records
        scores["cost"] = cost_fields(records, round(time.monotonic() - started, 3))
        failures["llm_output_invalid"] = invalid_attempts(records)
    if noise is not None:
        # 주 점수와 섞어 읽지 않게 범위 종류와 파일 지문을 남긴다
        scores["scope"] = {
            "kind": "noise",
            "file": cfg.noise_scope,
            "sha256": hashlib.sha256(noise_path.read_bytes()).hexdigest(),
            "docs_per_row_mean": sum(len(noise[r.row.row_id]) for r in results) / n,
        }
    return ScoreReport(scores=scores, rows=results, k_max=k_max)


def postgres_repo() -> ChunkRepository:
    """진짜 색인 DB 저장소 (DATABASE_URL). 테스트는 이 함수를 바꿔 끼운다."""
    return PostgresChunkRepository.from_url()


def first_hit_rank(r: RowResult) -> int | None:
    """처음 맞힌 순위 (1부터). 검색한 범위 안에 없으면 None."""
    for i, found in enumerate(r.found_by_rank):
        if found:
            return i + 1
    return None


def write_rows(report: ScoreReport, path: Path) -> None:
    """점수에 들어간 줄마다 한 줄씩 JSONL. 질의 글자는 쓰지 않는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in report.rows:
            line = {
                "row_id": r.row.row_id,
                "doc_ids": list(r.row.doc_ids or []),
                "first_hit_rank": first_hit_rank(r),
                # 채점 때 검색한 가장 큰 k. 이보다 큰 k로 비교하면 틀린 값이라 compare가 막는다
                "k_max": report.k_max,
            }
            if r.status_reason is not None:  # 출력을 못 읽은 줄만 표시 (다른 줄엔 키 없음)
                line["status_reason"] = r.status_reason
            f.write(json.dumps(line, ensure_ascii=False) + "\n")


def main(
    argv: list[str] | None = None,
    commit: str | None = None,
    # eval.common.paths.is_git_ignored(저장소 밖 통과)와 반대라 이름을 다르게 받았다
    ignored: Callable[[Path], bool] = git_ignored_strict,
) -> int:
    ap = argparse.ArgumentParser(prog="eval.retrieval.score")
    ap.add_argument("--config", required=True)
    ap.add_argument("--goldsets-root", default="data/goldsets")
    ap.add_argument("--chunks", default=None, help="조각 JSONL. 없으면 Postgres(DATABASE_URL)")
    ap.add_argument("--scores-dir", default=None)
    ap.add_argument("--cq-dir", default=None)
    ap.add_argument(
        "--cache-dir",
        default=None,
        help="모델 답 캐시 폴더 (whole_doc_llm은 필수, git 제외 경로만. 회마다 새 폴더)",
    )
    ap.add_argument("--rows-out", default=None, help="줄별 결과 JSONL (git 제외 경로만)")
    args = ap.parse_args(argv)

    # 줄별 결과 경로는 채점 전에 본다: 커밋될 수 있는 곳이면 아무것도 쓰지 않고 끝낸다
    rows_out = Path(args.rows_out).resolve() if args.rows_out else None
    if rows_out is not None and not ignored(rows_out):
        print(
            f"--rows-out 경로가 git 제외 확인 안 됨 (커밋될 수 있음): {rows_out}", file=sys.stderr
        )
        return 1

    # --chunks가 있으면 가짜 조각(출력은 work/), 없으면 진짜 색인 DB(출력은 experiments/)
    chunks_mode = args.chunks is not None
    try:
        cfg = load_config(args.config)
        run_context = None
        if cfg.impl == WHOLE_DOC_IMPL:
            # 같은 폴더를 몰래 다시 쓰지 않게 기본값이 없다. 캐시에 인용문헌 글자가 들어가
            # 커밋될 수 있는 곳이면 아무것도 쓰기 전에 멈춘다
            if args.cache_dir is None:
                print("whole_doc_llm 채점에는 --cache-dir가 필요하다", file=sys.stderr)
                return 1
            cache_dir = Path(args.cache_dir).resolve()
            if not ignored(cache_dir):
                print(
                    f"--cache-dir 경로가 git 제외 확인 안 됨 (커밋될 수 있음): {cache_dir}",
                    file=sys.stderr,
                )
                return 1
            run_context = new_run_context(cfg, cache_dir)
        if chunks_mode:
            repo = InMemoryChunkRepository.from_jsonl(cfg.corpus, args.chunks)
        else:
            repo = postgres_repo()
        scores_dir = (
            Path(args.scores_dir)
            if args.scores_dir
            else default_scores_dir(cfg.experiment, chunks_mode=chunks_mode)
        )
        cq_dir = Path(args.cq_dir) if args.cq_dir else default_cq_dir(cfg.experiment)
        report = score(
            cfg,
            repo,
            Path(args.goldsets_root),
            commit if commit is not None else git_commit(),
            chunks_mode=chunks_mode,
            scores_dir=scores_dir,
            cq_dir=cq_dir,
            run_context=run_context,
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
    # 필수 칸·꼴 검사 뒤 쓴다 (eval/common/scores.py)
    try:
        write_scores(scores_dir, report.scores)
    except RetrievalEvalError as e:
        print(f"채점 실패: {e}", file=sys.stderr)
        return 1
    if rows_out is not None:
        write_rows(report, rows_out)
    print(f"scores.json 저장: n={report.scores['n']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
