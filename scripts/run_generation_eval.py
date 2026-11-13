"""생성 단계 평가: 질문 파일 -> 검색 + 답변 생성 + 검증 -> 지표와 결과 파일.

예(개발): python scripts/run_generation_eval.py --questions data/eval/questions_d2_dev.jsonl \\
            --noanswer data/eval/questions_d2_noanswer.jsonl --retrieval-cache data/processed/gen_retrieval_dev.json
- 파일 이름에 sealed/holdout 이 들어간 질문 파일은 --final-holdout 없이는 거부한다(검색 평가와 같은 규칙).
- --retrieval-cache: 파일이 있으면 검색 결과를 재사용(생성 모델·프롬프트만 바꿔 비교할 때), 없으면 이번 검색 결과를
  이 경로에 새로 저장한다. 기존 파일은 덮어쓰지 않는다(캐시에 없는 질문은 실시간으로 검색하고 저장하지 않음).
- 정답 없음 질문 파일은 split 이 질문 파일 종류와 맞는 것만 쓴다(개발 파일 -> dev2, 봉인 파일 -> sealed2).
- 결과는 data/results/gen_<모델>_<질문파일>_<시각>.json 과 사람이 읽을 표본 .md 로 새 파일에만 저장한다. 키는 저장하지 않는다.
"""
import argparse
import hashlib
import json
import random
import re
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.eval.questions import corpus_gold, load_questions  # noqa: E402
from src.rag.ask import answer_question, error_text  # noqa: E402
from src.rag.evidence import Evidence  # noqa: E402
from src.rag.gen_metrics import summarize_answerable, summarize_noanswer  # noqa: E402
from src.rag.generate import PROMPTS, generate  # noqa: E402
from src.rag.pipeline import Retrieval, build_pipeline  # noqa: E402
from src.rag.settings import Settings, load_key  # noqa: E402

EMPTY_CHECKS = {"unknown_tags": [], "articles_outside_evidence": [], "numbers_not_in_evidence": [],
                "status_cited_mismatch": False}


def git_state() -> dict:
    def run(*a):
        return subprocess.run(["git", *a], capture_output=True, text=True).stdout.strip()
    return {"commit": run("rev-parse", "--short", "HEAD"), "dirty": bool(run("status", "--porcelain", "--", "src", "scripts"))}


def cache_meta(settings: Settings) -> dict:
    """검색 결과에 영향을 주는 설정만(생성 모델·프롬프트는 캐시와 무관). 캐시 재사용 때 현재 설정과 비교한다."""
    return {"corpus": str(settings.corpus), "chunk_emb": str(settings.chunk_emb), "expand_model": settings.expand_model,
            "rerank_model": settings.rerank_model, "rerank_window": settings.rerank_window,
            "n_evidence": settings.n_evidence, "max_evidence_chars": settings.max_evidence_chars}


def load_cache(path: Path | None) -> tuple[dict, dict[str, Retrieval]]:
    """(meta, {질문 id: Retrieval}). 예전 형식(메타 없는 평평한 dict)도 읽되 메타 검사는 못 한다."""
    if path is None or not path.exists():
        return {}, {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    meta, items = (raw.get("meta", {}), raw["items"]) if "items" in raw else ({}, raw)
    return meta, {qid: Retrieval(**{**d, "evidence": [Evidence(**e) for e in d["evidence"]]}) for qid, d in items.items()}


def check_cache(meta: dict, cache: dict, current: dict, rows: list, allow_miss: bool) -> None:
    """캐시가 지금 설정·질문과 맞는지 확인한다. 어긋나면 서로 다른 조건의 결과가 섞이지 않게 검색 전에 멈춘다."""
    diff = [k for k, v in meta.items() if k in current and current[k] != v]
    if diff:
        raise SystemExit(f"검색 캐시가 지금 설정과 다릅니다({', '.join(diff)}). 캐시를 새로 만드세요.")
    stale = [q.id for q in rows if q.id in cache and cache[q.id].question != q.question]
    if stale:
        raise SystemExit(f"검색 캐시의 질문 문장이 질문 파일과 다릅니다: {stale}. 캐시를 새로 만드세요.")
    missing = [q.id for q in rows if q.id not in cache]
    if missing and not allow_miss:
        raise SystemExit(f"검색 캐시에 없는 질문이 있습니다: {missing}. 실시간 검색으로 채우려면 --allow-cache-miss.")


def error_result(question: str, model: str, message: str) -> dict:
    """한 질문이 실패해도 평가 전체가 멈추지 않게, 오류를 결과로 남긴다(메시지에는 키가 없다)."""
    return {"question": question, "status": "error", "answer": "", "cited": [], "cited_articles": [], "evidence": [],
            "checks": dict(EMPTY_CHECKS), "retrieval": {}, "generation": {"model": model, "raw": ""},
            "seconds": {"retrieval": 0.0, "generation": 0.0}, "error": message[:200]}


def sample_markdown(answerable, noanswer, partial_ids, n, seed=20261113) -> str:
    """사람이 읽을 표본: 무작위 n개 + 부분 답변 질문 전부 + 정답 없음에 답을 만든 질문 전부."""
    rng = random.Random(seed)
    picked = {r["id"] for r in rng.sample(answerable, min(n, len(answerable)))} | (partial_ids & {r["id"] for r in answerable})
    rows = [r for r in answerable if r["id"] in picked] + [r for r in noanswer if r["result"]["status"] in ("answered", "partial")]
    out = ["# 답변 표본 (사람이 읽고 근거 충실성을 확인)\n"]
    for r in rows:
        res = r["result"]
        labels = {e["tag"]: e["label"] for e in res["evidence"]}
        out.append(f"## {r['id']} [{res['status']}] {res['question']}\n정답 조문: {r['gold'] or '(정답 없음)'}\n\n{res['answer']}\n")
        out.append("인용: " + (", ".join(f"{t} {labels.get(t, '?')}" for t in res["cited"]) or "(없음)"))
        warn = {k: v for k, v in res["checks"].items() if v}
        out.append(f"검증 경고: {json.dumps(warn, ensure_ascii=False) if warn else '없음'}\n")
    return "\n".join(out)


def main(argv=None, pipeline=None, generate_fn=None, anthropic_key=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", type=Path, required=True)
    ap.add_argument("--noanswer", type=Path, default=None)
    ap.add_argument("--final-holdout", action="store_true", help="봉인·홀드아웃 질문 최종 평가 때만")
    ap.add_argument("--generation-model", default=Settings().generation_model)
    ap.add_argument("--prompt-version", default=Settings().prompt_version, choices=sorted(PROMPTS), help="생성 프롬프트 버전(기본: 채택된 v2)")
    ap.add_argument("--allow-cache-miss", action="store_true", help="검색 캐시에 없는 질문을 실시간 검색으로 채움(저장은 하지 않음)")
    ap.add_argument("--retrieval-cache", type=Path, default=None)
    ap.add_argument("--limit", type=int, default=None, help="스모크용: 각 파일에서 앞 N개만")
    ap.add_argument("--sample", type=int, default=10, help="표본 .md 에 넣을 무작위 질문 수")
    ap.add_argument("--out-dir", type=Path, default=Path("data/results"))
    args = ap.parse_args(argv)

    label = args.questions.stem
    if ("sealed" in label or "holdout" in label) and not args.final_holdout:
        raise SystemExit("봉인·홀드아웃 질문은 최종 평가 때만 씁니다(--final-holdout 필요).")
    split = "sealed2" if "sealed" in label else "dev2"
    sealed_words = ("sealed", "holdout")

    def is_sealed(s: str) -> bool:
        return any(w in s for w in sealed_words)

    if args.noanswer and is_sealed(args.noanswer.stem) and not args.final_holdout:
        raise SystemExit("봉인·홀드아웃 정답 없음 파일은 최종 평가 때만 씁니다(--final-holdout 필요).")

    questions = load_questions(args.questions)
    noanswer = [q for q in load_questions(args.noanswer) if q.split == split] if args.noanswer else []
    if not args.final_holdout and any(is_sealed(q.split) for q in questions + noanswer):
        # 파일 이름은 평범한데 안에 봉인 질문(split=sealed2)이 든 파일(예: 정답 없음 파일)을 --questions 로 주는 우회를 막는다
        raise SystemExit("봉인·홀드아웃 질문(split)이 들어 있습니다. 최종 평가 때만 씁니다(--final-holdout 필요).")
    if args.limit is not None:  # 0 도 '아무것도 돌리지 않음'으로 존중한다(예전에는 무시되어 전체 평가가 시작된 적이 있음)
        questions, noanswer = questions[:args.limit], noanswer[:args.limit]

    settings = Settings(generation_model=args.generation_model, prompt_version=args.prompt_version)
    meta, cache = load_cache(args.retrieval_cache)
    using_cache = args.retrieval_cache is not None and args.retrieval_cache.exists()
    if using_cache:
        check_cache(meta, cache, cache_meta(settings), questions + noanswer, args.allow_cache_miss)
    write_cache = args.retrieval_cache is not None and not using_cache
    pipeline = pipeline or build_pipeline(settings)
    key = anthropic_key or load_key("ANTHROPIC_API_KEY", settings.env_path)
    new_cache: dict[str, dict] = {}
    retrieval_failed: list[str] = []

    def run_one(q):
        retrieval, retrieval_seconds = cache.get(q.id), 0.0  # 캐시를 쓴 질문의 검색 시간은 0(측정 안 함)
        from_cache = retrieval is not None
        try:
            if retrieval is None:
                t0 = time.perf_counter()
                try:
                    retrieval = pipeline.retrieve(q.question)
                except Exception:
                    retrieval_failed.append(q.id)  # 일부만 든 캐시를 저장하지 않기 위해 기록
                    raise
                retrieval_seconds = time.perf_counter() - t0
            if write_cache:
                new_cache[q.id] = asdict(retrieval)
            res = answer_question(q.question, pipeline, settings, key, retrieval=retrieval, generate_fn=generate_fn)
            res["seconds"]["retrieval"] = retrieval_seconds
        except Exception as e:  # 한 질문의 실패가 전체 평가를 멈추지 않게
            res = error_result(q.question, settings.generation_model, error_text(e))  # 인증 오류 본문은 버린다
        return {"id": q.id, "gold": list(corpus_gold(q.gold)), "retrieval_from_cache": from_cache, "result": res}

    answerable = [run_one(q) for q in questions]
    noans = [run_one(q) for q in noanswer]

    if write_cache and not retrieval_failed:
        try:  # "x": 실행 도중 같은 경로에 다른 실행이 캐시를 만들었다면 덮어쓰지 않고 멈춘다
            with open(args.retrieval_cache, "x", encoding="utf-8") as f:
                f.write(json.dumps({"meta": cache_meta(settings), "items": new_cache}, ensure_ascii=False))
        except FileExistsError:
            raise SystemExit(f"검색 캐시가 실행 중에 다른 곳에서 만들어졌습니다. 덮어쓰지 않습니다: {args.retrieval_cache}")
    elif write_cache:
        print(f"[경고] 검색이 실패한 질문이 있어 검색 캐시를 저장하지 않았습니다: {retrieval_failed}")

    now = datetime.now()
    stem = f"gen_{args.generation_model}{'' if args.prompt_version == 'v1' else '-' + args.prompt_version}_{label}_{now.strftime('%Y%m%d-%H%M%S')}"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_json, out_md = args.out_dir / f"{stem}.json", args.out_dir / f"{stem}.md"
    if out_json.exists() or out_md.exists():
        sys.exit(f"이미 있는 파일이라 덮어쓰지 않습니다: {out_json}")
    gen_secs = [r["result"]["seconds"]["generation"] for r in answerable + noans if r["result"]["status"] != "error"]
    ret_secs = [r["result"]["seconds"]["retrieval"] for r in answerable + noans if r["result"]["seconds"]["retrieval"] > 0]
    partial_ids = {q.id for q in questions if "부분 답변" in q.note}
    payload = {
        "config": {"generation_model": args.generation_model, "prompt_version": args.prompt_version,
                   "prompt_sha256": hashlib.sha256(PROMPTS[args.prompt_version].encode("utf-8")).hexdigest()[:16],
                   "questions": str(args.questions), "noanswer": str(args.noanswer) if args.noanswer else None, "split": split,
                   "retrieval_cache": str(args.retrieval_cache) if args.retrieval_cache else None, "limit": args.limit,
                   "n_evidence": settings.n_evidence, "max_evidence_chars": settings.max_evidence_chars},
        "run_at": now.isoformat(timespec="seconds"), "git": git_state(),
        "summary_answerable": summarize_answerable(answerable), "summary_noanswer": summarize_noanswer(noans),
        # 부분 답변 질문(질문 파일 note 의 "부분 답변" 표시)만 따로: 부분 답변 정책이 지켜지는지 본다
        "summary_partial_flagged": summarize_answerable([r for r in answerable if r["id"] in partial_ids]),
        "mean_seconds": {"generation": sum(gen_secs) / len(gen_secs) if gen_secs else None,
                         "retrieval": sum(ret_secs) / len(ret_secs) if ret_secs else None},
        "answerable": answerable, "noanswer": noans,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    out_md.write_text(sample_markdown(answerable, noans, partial_ids, args.sample), encoding="utf-8")

    sa, sn = payload["summary_answerable"], payload["summary_noanswer"]
    pf = payload["summary_partial_flagged"]
    print(f"정답 있음 n={sa['n']}: 정답 조문 인용 {sa['cited_gold']}, answered {sa['answered']}, partial {sa['partial']}, "
          f"no_basis {sa['no_basis']}, error {sa['error']}, 검증 경고 {sa['check_failures']} {sa['by_check']}, 반말체 추정 {sa['plain_style']}")
    if pf["n"]:
        print(f"부분 답변 표시 질문 n={pf['n']}: answered {pf['answered']}, partial {pf['partial']}, no_basis {pf['no_basis']}, 정답 조문 인용 {pf['cited_gold']}")
    if noans:
        print(f"정답 없음 n={sn['n']}: no_basis {sn['no_basis']}, 답을 만듦 {sn['fabricated']} {sn['fabricated_ids']}, error {sn['error']}")
    print(f"평균 소요(초): {payload['mean_seconds']}\n-> {out_json}\n-> {out_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
