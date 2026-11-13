"""생성 평가 결과(gen_*.json)를 opus 로 채점한다: 근거 충실성·정확성·완결성·판정 적절성.

예: python scripts/judge_generation.py --results data/results/gen_claude-sonnet-5-5-v3_questions_d2_dev_XXXX.json --limit 3
- 근거 조문 본문은 그 결과가 쓴 검색 캐시(config.retrieval_cache)에서, 정답 조문 본문은 조문 단위 청크 파일에서 읽는다.
- 봉인(sealed) 결과는 --final-holdout 없이는 거부한다(이미 최종 평가에 쓴 세트라 개발 중 채점에 쓰지 않는다).
- 결과는 data/results/judge_<채점모델>_<결과파일이름>_<시각>.json 에 새 파일로만 저장한다. 키는 저장하지 않는다.
"""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rag.articles import get_article, load_articles  # noqa: E402
from src.rag.ask import error_text  # noqa: E402
from src.rag.gen_metrics import summarize_usage  # noqa: E402
from src.rag.judge import judge, summarize_judgments  # noqa: E402
from src.rag.settings import Settings, load_key  # noqa: E402
from src.retrieval import usage  # noqa: E402

MAX_CHARS = 4000


def load_cache_texts(path: Path) -> dict[str, dict[str, str]]:
    """검색 캐시 -> {질문 id: {조문 id: 본문}}. 예전 형식(메타 없는 평평한 dict)도 읽는다."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items = raw["items"] if "items" in raw else raw
    return {qid: {e["article_id"]: e["text"] for e in d["evidence"]} for qid, d in items.items()}


def judge_item(item: dict, kind: str, texts: dict[str, str], articles: dict, model: str, key: str, judge_fn=judge) -> dict:
    res = item["result"]
    evidence = [(e["label"], texts.get(e["article_id"], "(본문을 찾지 못함)")) for e in res["evidence"]]
    gold = []
    for aid in item["gold"]:
        art = get_article(articles, aid)
        if art:
            gold.append((art["label"], art["text"][:MAX_CHARS]))
    with usage.capture() as recs:
        try:
            j = judge_fn(res["question"], evidence, gold, res["status"], res["answer"], model, key)
        except Exception as e:  # 한 건의 실패가 전체를 멈추지 않게(인증 오류 본문은 버린다)
            j = {"error": error_text(e)[:200]}
    return {"id": item["id"], "kind": kind, "status": res["status"], "judgment": j, "usage": usage.summarize(recs)}


def main(argv=None, judge_fn=judge, key=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, required=True, help="gen_*.json 결과 파일")
    ap.add_argument("--judge-model", default="claude-opus-5-5")
    ap.add_argument("--final-holdout", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="시험용: 정답 있음/없음 각각 앞 N개만")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--article-corpus", type=Path, default=Settings().article_corpus, help="정답 조문 본문을 읽을 조문 단위 청크 파일")
    ap.add_argument("--out-dir", type=Path, default=Path("data/results"))
    args = ap.parse_args(argv)

    data = json.loads(args.results.read_text(encoding="utf-8"))
    cfg = data["config"]
    if ("sealed" in cfg["questions"] or "holdout" in cfg["questions"]) and not args.final_holdout:
        raise SystemExit("봉인·홀드아웃 결과는 최종 평가 때만 채점합니다(--final-holdout 필요).")
    if not cfg.get("retrieval_cache"):
        raise SystemExit("이 결과에는 검색 캐시 경로가 없어 근거 조문 본문을 찾을 수 없습니다.")
    cache = load_cache_texts(Path(cfg["retrieval_cache"]))
    settings = Settings()
    articles = load_articles(args.article_corpus)
    key = key or load_key("ANTHROPIC_API_KEY", settings.env_path)

    ans, noans = data["answerable"], data["noanswer"]
    if args.limit is not None:
        ans, noans = ans[:args.limit], noans[:args.limit]
    jobs = [(i, "answerable") for i in ans if i["result"]["status"] != "error"] + \
           [(i, "noanswer") for i in noans if i["result"]["status"] != "error"]
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        rows = list(ex.map(lambda j: judge_item(j[0], j[1], cache.get(j[0]["id"], {}), articles, args.judge_model, key, judge_fn), jobs))

    now = datetime.now()
    out = args.out_dir / f"judge_{args.judge_model}_{args.results.stem}_{now.strftime('%Y%m%d-%H%M%S')}.json"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if out.exists():
        sys.exit(f"이미 있는 파일이라 덮어쓰지 않습니다: {out}")
    total_usage = usage.merge({}, {})
    for r in rows:
        total_usage = usage.merge(total_usage, r["usage"])
    usd, unpriced = usage.cost_of(total_usage)
    payload = {"config": {"judge_model": args.judge_model, "results": str(args.results), "generation_model": cfg["generation_model"],
                          "prompt_version": cfg["prompt_version"], "limit": args.limit},
               "run_at": now.isoformat(timespec="seconds"),
               "summary": summarize_judgments(rows),
               "summary_answerable": summarize_judgments([r for r in rows if r["kind"] == "answerable"]),
               "summary_noanswer": summarize_judgments([r for r in rows if r["kind"] == "noanswer"]),
               "usage": total_usage, "cost_usd": usd, "cost_per_item_usd": usd / len(rows) if rows else 0.0, "unpriced_models": unpriced,
               "rows": rows}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    for name in ("summary_answerable", "summary_noanswer"):
        s = payload[name]
        m = {k: (None if v is None else round(v, 2)) for k, v in s["mean"].items()}
        print(f"{name}: n={s['n']} 오류={s['errors']} 평균 {m} 판정 적절 {s['status_ok']}/{s['n']} 3점 이하 {s['low_ids']}")
    print(f"채점 토큰(단계:모델 → 호출/입력/출력): " + "; ".join(
        f"{k} → {v['calls']}/{v['input_tokens']}/{v['output_tokens']}" for k, v in total_usage["by_stage"].items()))
    print(f"채점 비용 ${usd:.4f} (건당 ${payload['cost_per_item_usd']:.4f})\n-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
