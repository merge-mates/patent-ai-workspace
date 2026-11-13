"""질의 확장 결과 만들기 (사용자 Mac 터미널에서 실행; 작업 VM 은 api.openai.com 에 접속 불가).

  python scripts/expand_queries.py --model <모델명> --dry-run
  python scripts/expand_queries.py --model <모델명> --split dev
결과는 data/processed/expansions_<model>_<split>_<시각>.json 에 새 파일로 저장(덮어쓰지 않음, git 미추적).
홀드아웃은 최종 평가 때만 쓰므로 --final-holdout 플래그 없이는 거부한다.
LLM 에 보내는 것은 질문 문장뿐이다. API 키는 출력하지 않는다.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.eval.questions import load_questions  # noqa: E402
from src.retrieval.openai_embed import load_api_key  # noqa: E402
from src.retrieval.query_expand import (PROMPT_VERSION, PROMPTS, expand_one,  # noqa: E402
                                        expanded_query, has_article_number, parse_terms)


def main(argv=None, expand=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--split", default="dev", choices=["dev", "holdout"])
    ap.add_argument("--questions", type=Path, default=None, help="질문 파일 경로(지정하면 --split 대신 파일 이름이 split 이름표)")
    ap.add_argument("--prompt-version", default=PROMPT_VERSION, choices=sorted(PROMPTS), help="확장 프롬프트 버전")
    ap.add_argument("--final-holdout", action="store_true", help="홀드아웃 최종 평가 때만")
    ap.add_argument("--no-temperature", action="store_true", help="temperature 를 보내지 않음(지정을 못 받는 모델용)")
    ap.add_argument("--dry-run", action="store_true", help="API 호출 없이 개수와 프롬프트만 출력")
    ap.add_argument("--out-dir", type=Path, default=Path("data/processed"))
    args = ap.parse_args(argv)

    if args.questions:
        args.split = args.questions.stem
    if ("holdout" in args.split or "sealed" in args.split) and not args.final_holdout:
        sys.exit("홀드아웃·봉인 질문은 최종 평가 때만 씁니다(--final-holdout 필요).")

    if args.questions:
        qs = load_questions(args.questions)
    else:
        qs = load_questions(split="dev", law="특허법") if args.split == "dev" else load_questions(split="holdout")
    print(f"질문 {len(qs)}개, 모델 {args.model}, 프롬프트 {args.prompt_version}")
    if args.dry_run:
        print("[시스템 프롬프트]\n" + PROMPTS[args.prompt_version])
        print("[사용자 메시지 예] " + qs[0].question)
        return 0

    temperature = None if args.no_temperature else 0
    if expand is None:
        expand = lambda q, m, k: expand_one(q, m, k, temperature=temperature, version=args.prompt_version)  # noqa: E731
    key = load_api_key()
    items = []
    for q in qs:
        raw = expand(q.question, args.model, key)
        terms = parse_terms(raw)
        items.append({"id": q.id, "question": q.question, "raw": raw, "terms": terms,
                      "raw_had_article_number": has_article_number(raw),
                      "query": expanded_query(q.question, terms)})
    out = args.out_dir / f"expansions_{args.model}{'' if args.prompt_version == PROMPT_VERSION else '-' + args.prompt_version}_{args.split}_{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    if out.exists():
        sys.exit(f"이미 있는 파일이라 덮어쓰지 않습니다: {out}")
    payload = {"meta": {"model": args.model, "prompt_version": args.prompt_version, "temperature": temperature,
                        "prompt_sha256": hashlib.sha256(PROMPTS[args.prompt_version].encode("utf-8")).hexdigest()[:16],
                        "split": args.split, "n": len(items),
                        "created": datetime.now().isoformat(timespec="seconds")},
               "items": items}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    flagged = sum(i["raw_had_article_number"] for i in items)
    print(f"저장: {out} (조문 번호가 섞여 나온 응답 {flagged}개, 해당 항목만 걸러냄)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
