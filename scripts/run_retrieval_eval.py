"""검색 실험 실행: 질문 파일 + 청크 파일 -> 질문별 정답 순위와 요약을 새 JSON 으로 저장.

예: python scripts/run_retrieval_eval.py --method m1 --split dev
방식(--method): m4a = M2a+M3 RRF, m4b = M2b+M3 RRF, m3 = OpenAI 임베딩(미리 만든 벡터 파일 필요, --chunk-emb/--question-emb), m1 = BM25 공백 토큰, m2a = BM25 형태소(kiwipiepy), m2b = BM25 글자 2-gram, m2c = BM25 글자 3-gram.
결과는 data/results/ 에 새 파일로만 저장한다(덮어쓰지 않음).
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.eval.metrics import rank_of_gold, summarize  # noqa: E402
from src.eval.questions import corpus_gold, corpus_law, load_questions  # noqa: E402
from src.retrieval.fusion import HybridRetriever, collapse_to_articles  # noqa: E402
from src.retrieval.dense import DenseRetriever, load_embeddings  # noqa: E402
from src.retrieval.bm25 import Bm25Retriever, whitespace_tokenizer  # noqa: E402
from src.retrieval.query_expand import queries_by_id  # noqa: E402
from src.retrieval.llm_rerank import PROMPT_VERSION as LLM_RERANK_PROMPT, article_texts, llm_rerank  # noqa: E402
from src.retrieval.openai_embed import load_api_key  # noqa: E402
from src.retrieval.rerank import apply_rerank, build_links  # noqa: E402
from src.retrieval.tokenizers import char_ngram_tokenizer, kiwi_tokenizer  # noqa: E402

DEFAULT_CORPUS = Path("data/processed/chunks_특허법_279827_20251111.jsonl")
CHUNK_DEPTH = 100  # 검색기에서 가져오는 청크 수(항 단위 청크는 한 조문이 여러 자리를 차지함)
ARTICLE_CUTOFF = 20  # 조문 단위로 묶은 뒤 이 순위 안에 정답이 없으면 순위 없음(>20)


def git_state() -> dict:
    def run(*a):
        return subprocess.run(["git", *a], capture_output=True, text=True).stdout.strip()
    return {"commit": run("rev-parse", "--short", "HEAD"), "dirty": bool(run("status", "--porcelain", "--", "src", "scripts"))}


def latest(pattern: str) -> Path:
    files = sorted(Path("data/processed").glob(pattern))
    if not files:
        raise SystemExit(f"벡터 파일이 없습니다: data/processed/{pattern}")
    return files[-1]


def build_retriever(method: str, chunks: list[dict], args=None):
    if method == "m1":
        return Bm25Retriever(chunks, tokenizer=whitespace_tokenizer)
    if method == "m3":
        c_path = args.chunk_emb or latest("emb_*_chunks_*.json")
        q_path = args.expanded_emb or args.question_emb or latest("emb_*_questions_*.json")
        meta_c, ids, mat = load_embeddings(c_path)
        meta_q, qids, qmat = load_embeddings(q_path)
        if meta_c["model"] != meta_q["model"]:
            raise SystemExit("조문과 질문의 임베딩 모델이 다릅니다.")
        if ids != [c["chunk_id"] for c in chunks]:
            raise SystemExit("벡터 파일의 청크 id 가 코퍼스와 다릅니다(순서 포함). 임베딩을 다시 만드세요.")
        if args.query_of is not None:  # 질의 확장: 확장 질의 문장으로 벡터를 찾는다
            if qids != list(args.query_of):
                raise SystemExit("확장 질의 임베딩의 질문 id 가 확장 파일/평가 질문과 다릅니다.")
            text_by_id = args.query_of
        else:
            text_by_id = {q.id: q.question for q in args.questions_list}
            if len({q.question for q in args.questions_list}) != len(args.questions_list):
                raise SystemExit("질문 문장이 중복되어 질문 벡터를 문장으로 찾을 수 없습니다.")
        args.embedding_info = {"model": meta_c["model"], "dims": meta_c["dims"],
                               "chunk_emb": c_path.name, "question_emb": q_path.name}
        return DenseRetriever(ids, mat, {text_by_id[i]: v for i, v in zip(qids, qmat)})
    if method in ("m4a", "m4b"):
        bm25 = build_retriever("m2a" if method == "m4a" else "m2b", chunks, args)
        dense = build_retriever("m3", chunks, args)
        return HybridRetriever([bm25, dense])
    if method == "m2a":
        return Bm25Retriever(chunks, tokenizer=kiwi_tokenizer)
    if method == "m2b":
        return Bm25Retriever(chunks, tokenizer=char_ngram_tokenizer(2))
    if method == "m2c":
        return Bm25Retriever(chunks, tokenizer=char_ngram_tokenizer(3))
    raise SystemExit(f"알 수 없는 방식: {method}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", required=True)
    ap.add_argument("--split", default="dev", choices=["dev", "holdout"])
    ap.add_argument("--questions", type=Path, default=None,
                    help="질문 파일 경로(없으면 data/eval/questions.jsonl 을 --split 으로 거름). 봉인 질문 파일은 --final-holdout 필요")
    ap.add_argument("--final-holdout", action="store_true", help="홀드아웃·봉인 질문 최종 평가 때만")
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    ap.add_argument("--tag", default="", help="변형 실험 이름(결과 파일명·설정에 기록)")
    ap.add_argument("--chunk-emb", type=Path, default=None)
    ap.add_argument("--question-emb", type=Path, default=None)
    ap.add_argument("--expansions", type=Path, default=None, help="질의 확장 파일(expand_queries.py 결과)")
    ap.add_argument("--expanded-emb", type=Path, default=None, help="확장 질의 임베딩(embed_openai.py --what expanded 결과)")
    ap.add_argument("--rerank", default="none", choices=["none", "law_first", "link_pairs"],
                    help="순위 후처리(src/retrieval/rerank.py, Phase 6 실험 ③)")
    ap.add_argument("--llm-rerank-model", default=None,
                    help="LLM 재순위에 쓸 모델명(검색 상위 10개를 질문과 함께 보여 주고 다시 정렬; 질문마다 호출 1회)")
    ap.add_argument("--out-dir", type=Path, default=Path("data/results"))
    args = ap.parse_args(argv)

    chunks = [json.loads(l) for l in args.corpus.read_text(encoding="utf-8").splitlines() if l.strip()]
    corpus_laws = sorted({c["chunk_id"].split("#")[0] for c in chunks})
    if args.questions:  # 질문 파일을 직접 지정: 파일 이름(확장자 뺀 것)을 split 이름표로 쓴다
        args.split = args.questions.stem
        if "sealed" in args.split and not args.final_holdout:
            raise SystemExit("봉인 질문은 최종 평가 때만 씁니다(--final-holdout 필요).")
        all_questions = load_questions(args.questions)
    else:
        if args.split == "holdout" and not args.final_holdout:
            raise SystemExit("홀드아웃 질문은 최종 평가 때만 씁니다(--final-holdout 필요).")
        all_questions = load_questions(split=args.split)
    args.questions_list = all_questions
    questions = [q for q in all_questions if corpus_law(q.law) in corpus_laws]
    args.embedding_info = None
    args.query_of = None
    expansion_info = None
    if args.expansions or args.expanded_emb:
        if not args.expansions:
            raise SystemExit("--expanded-emb 는 --expansions 와 함께 써야 합니다.")
        exp = json.loads(args.expansions.read_text(encoding="utf-8"))
        if exp["meta"]["split"] != args.split:
            raise SystemExit(f"확장 파일의 split({exp['meta']['split']})이 --split({args.split})과 다릅니다.")
        args.query_of = queries_by_id(exp, [q.id for q in questions])
        expansion_info = {"file": args.expansions.name, "model": exp["meta"]["model"],
                          "prompt_version": exp["meta"]["prompt_version"]}
        if args.method in ("m3", "m4a", "m4b") and not args.expanded_emb:
            raise SystemExit("임베딩 방식에는 --expanded-emb 가 필요합니다.")
    retriever = build_retriever(args.method, chunks, args)
    links = build_links(chunks) if args.rerank == "link_pairs" else None
    if args.llm_rerank_model:
        art_text, llm_key = article_texts(chunks), load_api_key()

    rows, ranks = [], []
    for q in questions:
        ranked = collapse_to_articles([cid for cid, _ in retriever.search(args.query_of[q.id] if args.query_of else q.question, top_n=CHUNK_DEPTH)])
        ranked = apply_rerank(args.rerank, ranked, links)
        llm_raw = None
        if args.llm_rerank_model:  # 원 질문(확장 전)을 보여 준다
            ranked, llm_raw = llm_rerank(q.question, ranked, art_text, args.llm_rerank_model, llm_key)
        rank = rank_of_gold(ranked, corpus_gold(q.gold), max_rank=ARTICLE_CUTOFF)
        if rank is None and len(ranked) < ARTICLE_CUTOFF:
            print(f"  [경고] {q.id}: 청크 {CHUNK_DEPTH}개가 조문 {len(ranked)}개로 묶여 컷오프({ARTICLE_CUTOFF}) 미만 - 순위 없음이 컷오프 탓일 수 있음")
        ranks.append(rank)
        rows.append({"id": q.id, "question": q.question, "gold": list(corpus_gold(q.gold)), "rank": rank,
                     "top5": ranked[:5], **({"llm_raw": llm_raw} if llm_raw is not None else {})})

    now = datetime.now()
    result = {
        "config": {"method": args.method, "split": args.split, "corpus": str(args.corpus),
                   "corpus_chunks": len(chunks), "corpus_laws": corpus_laws, "chunk_depth": CHUNK_DEPTH, "article_cutoff": ARTICLE_CUTOFF,
                   "embedding": args.embedding_info, "expansion": expansion_info,
                   "rerank": args.rerank, "llm_rerank": ({"model": args.llm_rerank_model, "prompt_version": LLM_RERANK_PROMPT, "window": 10} if args.llm_rerank_model else None), "tag": args.tag or None, "questions_total": len(all_questions), "questions_excluded": len(all_questions) - len(questions)},
        "run_at": now.isoformat(timespec="seconds"),
        "git": git_state(),
        "summary": summarize(ranks),
        "questions": rows,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"-{args.tag}" if args.tag else ""
    out = args.out_dir / f"{args.method}{tag}_{args.split}_{now.strftime('%Y%m%d-%H%M%S')}.json"
    if out.exists():
        sys.exit(f"이미 있는 파일이라 덮어쓰지 않습니다: {out}")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    s = result["summary"]
    print(f"{args.method} / {args.split}: n={s['n']} Hit@1={s['hit@1']} Hit@3={s['hit@3']} "
          f"Hit@5={s['hit@5']} MRR={s['mrr']:.3f}  -> {out}")
    for r in rows:
        print(f"  {r['id']} rank={r['rank']} gold={r['gold']} top3={r['top5'][:3]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
