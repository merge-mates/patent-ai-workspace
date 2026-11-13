"""OpenAI 임베딩 만들기 (사용자 Mac 터미널에서 실행; 작업 VM 은 api.openai.com 에 접속 불가).

  python scripts/embed_openai.py --what chunks --dry-run
  python scripts/embed_openai.py --what chunks
  python scripts/embed_openai.py --what questions --split dev
  python scripts/embed_openai.py --what expanded --expansions data/processed/expansions_<...>.json
결과는 data/processed/emb_<model>_<what>_<시각>.json 에 새 파일로 저장(덮어쓰지 않음, git 미추적).
홀드아웃 질문은 최종 평가 때만 쓰므로 --final-holdout 플래그 없이는 임베딩을 거부한다.
보내는 것: 공개 법령 조문 텍스트 또는 평가 질문뿐. API 키는 출력하지 않는다.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.eval.questions import load_questions  # noqa: E402
from src.retrieval.openai_embed import DEFAULT_MODEL, embed_texts, load_api_key  # noqa: E402

CHUNKS = Path("data/processed/chunks_특허법_279827_20251111.jsonl")


def main(argv=None, embed=embed_texts) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--what", required=True, choices=["chunks", "questions", "expanded"])
    ap.add_argument("--split", default="dev", choices=["dev", "holdout"])
    ap.add_argument("--questions", type=Path, default=None, help="--what questions 일 때 질문 파일 경로(파일 이름이 split 이름표)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--chunks", type=Path, default=CHUNKS)
    ap.add_argument("--expansions", type=Path, default=None, help="--what expanded 일 때: expand_queries.py 결과 파일")
    ap.add_argument("--tag", default="", help="변형 실험 이름(파일명에 들어감, 예: noheader)")
    ap.add_argument("--final-holdout", action="store_true", help="홀드아웃 최종 평가 때만")
    ap.add_argument("--dry-run", action="store_true", help="API 호출 없이 개수·대략 토큰만 출력")
    ap.add_argument("--out-dir", type=Path, default=Path("data/processed"))
    args = ap.parse_args(argv)

    if args.what == "questions" and args.questions:
        args.split = args.questions.stem
    if args.what == "questions" and ("holdout" in args.split or "sealed" in args.split) and not args.final_holdout:
        sys.exit("홀드아웃 질문은 최종 평가 때만 씁니다(--final-holdout 필요).")

    exp_meta = None
    if args.what == "expanded":
        if args.expansions is None:
            sys.exit("--what expanded 에는 --expansions 파일이 필요합니다.")
        exp = json.loads(args.expansions.read_text(encoding="utf-8"))
        exp_meta = exp["meta"]
        if ("holdout" in exp_meta["split"] or "sealed" in exp_meta["split"]) and not args.final_holdout:
            sys.exit("홀드아웃 확장 질의는 최종 평가 때만 씁니다(--final-holdout 필요).")
        ids, texts = [i["id"] for i in exp["items"]], [i["query"] for i in exp["items"]]
    elif args.what == "chunks":
        rows = [json.loads(l) for l in args.chunks.read_text(encoding="utf-8").splitlines() if l.strip()]
        ids, texts = [r["chunk_id"] for r in rows], [r["text"] for r in rows]
    else:
        if args.questions:
            qs = load_questions(args.questions)
        else:
            qs = load_questions(split=args.split, law="특허법") if args.split == "dev" else load_questions(split="holdout")
        ids, texts = [q.id for q in qs], [q.question for q in qs]

    chars = sum(len(t) for t in texts)
    print(f"{args.what}: {len(texts)}개, 글자 {chars:,}자 (대략 토큰 {int(chars * 0.9):,}~{chars * 2:,}), 모델 {args.model}")
    if args.dry_run:
        return 0

    vectors = embed(texts, args.model, load_api_key())
    tag = f"-{args.tag}" if args.tag else ""
    out = args.out_dir / f"emb_{args.model}_{args.what}{tag}_{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    if out.exists():
        sys.exit(f"이미 있는 파일이라 덮어쓰지 않습니다: {out}")
    payload = {"meta": {"model": args.model, "dims": len(vectors[0]), "n": len(vectors), "what": args.what,
                        "split": args.split if args.what == "questions" else (exp_meta["split"] if exp_meta else None), "tag": args.tag or None, "source": str(args.chunks) if args.what == "chunks" else (str(args.expansions) if exp_meta else None),
                        "expansion": ({"model": exp_meta["model"], "prompt_version": exp_meta["prompt_version"]} if exp_meta else None),
                        "created": datetime.now().isoformat(timespec="seconds")},
               "ids": ids, "vectors": vectors}
    out.write_text(json.dumps(payload), encoding="utf-8")
    print(f"저장: {out} (차원 {len(vectors[0])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
