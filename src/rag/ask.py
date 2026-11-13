"""질문 → 근거 조문 → 답변 → 검증을 한 번에 돌리는 진입점.

터미널: python -m src.rag.ask "질문" [--model claude-haiku-5-5] [--json]
결과 딕셔너리에는 API 키가 들어가지 않는다. 근거 본문은 넣지 않는다(조문 id 와 라벨만).
"""
import argparse
import hashlib
import json
import re
import sys
import time

from src.rag.display import render_answer
from src.rag.generate import PROMPTS, generate
from src.rag.pipeline import Pipeline, Retrieval, build_pipeline
from src.rag.settings import Settings, load_key
from src.rag.verify import check_answer
from src.retrieval import usage


def answer_question(question: str, pipeline: Pipeline, settings: Settings, anthropic_key: str,
                    retrieval: Retrieval | None = None, generate_fn=None) -> dict:
    """retrieval 이 주어지면 검색을 건너뛴다(평가에서 저장된 검색 결과를 재사용할 때).
    generate_fn 을 안 주면 설정의 프롬프트 버전(기본 v2, 채택된 설정)으로 생성한다."""
    if generate_fn is None:
        generate_fn = lambda q, ev, m, k, t: generate(q, ev, m, k, t, version=settings.prompt_version)  # noqa: E731
    t0 = time.perf_counter()
    if retrieval is None:
        retrieval = pipeline.retrieve(question)
        retrieval_seconds = time.perf_counter() - t0
    else:
        retrieval_seconds = 0.0
    t1 = time.perf_counter()
    with usage.capture() as recs:  # 생성 호출의 토큰 사용량
        gen = generate_fn(question, retrieval.evidence, settings.generation_model, anthropic_key, settings.max_tokens)
    generation_seconds = time.perf_counter() - t1

    by_tag = {e.tag: e.article_id for e in retrieval.evidence}
    cited_articles = list(dict.fromkeys(by_tag[t] for t in gen["cited"] if t in by_tag))  # 없는 꼬리표는 뺀다
    evidence_view = [{"tag": e.tag, "article_id": e.article_id, "label": e.label, "truncated": e.truncated}
                     for e in retrieval.evidence]
    labels = {e["article_id"]: e["label"] for e in evidence_view}
    return {
        "question": question,
        "status": gen["status"],
        "answer": gen["answer"],
        "answer_display": render_answer(gen["answer"], evidence_view),  # 화면용: 꼬리표를 조문 이름으로 치환
        "citations": [{"article_id": a, "label": labels[a]} for a in cited_articles],  # 화면용: 눌러서 원문을 볼 조문
        "cited": gen["cited"],
        "cited_articles": cited_articles,
        "evidence": evidence_view,
        "checks": check_answer(gen["status"], gen["answer"], gen["cited"], retrieval.evidence),
        "retrieval": {"query": retrieval.query, "expansion_raw": retrieval.expansion_raw, "terms": retrieval.terms,
                      "ranked": retrieval.ranked, "rerank_raw": retrieval.rerank_raw},
        "generation": {"model": settings.generation_model, "prompt_version": settings.prompt_version,
                       "prompt_sha256": hashlib.sha256(PROMPTS[settings.prompt_version].encode("utf-8")).hexdigest()[:16],
                       "raw": gen["raw"]},
        "usage": usage.merge(retrieval.usage, usage.summarize(recs)),  # 검색 + 생성 토큰 사용량(예전 캐시는 검색 부분이 비어 있음)
        "seconds": {"retrieval": retrieval_seconds, "generation": generation_seconds},
    }


def error_text(e: Exception) -> str:
    """사용자에게 보여 줄 한 줄 오류 문장. 키가 섞이지 않게 예외 종류와 우리가 만든 메시지만 쓰고,
    인증 오류(HTTP 401/403)의 응답 본문(키 일부가 들어 있을 수 있음)은 버린다."""
    if isinstance(e, FileNotFoundError):
        return ".env 파일을 찾을 수 없습니다. .env 에 OPENAI_API_KEY, ANTHROPIC_API_KEY 값이 필요합니다."
    msg = f"{type(e).__name__}: {e}"
    return re.sub(r"(HTTP (?:401|403)).*", r"\1 (응답 본문은 기록하지 않음)", msg, flags=re.S).replace("\n", " ")


def format_result(r: dict) -> str:
    labels = {e["tag"]: e["label"] for e in r["evidence"]}
    lines = [f"[{r['status']}] {r['answer_display']}", "", "근거 조문:"]
    lines += [f"  {t} {labels.get(t, '(없는 꼬리표)')}" for t in r["cited"]] or ["  (인용 없음)"]
    warn = {k: v for k, v in r["checks"].items() if v}
    if warn:
        lines += ["", f"검증 경고: {json.dumps(warn, ensure_ascii=False)}"]
    s = r["seconds"]
    lines += ["", f"소요: 검색 {s['retrieval']:.1f}초, 생성 {s['generation']:.1f}초 ({r['generation']['model']})"]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--model", default=Settings().generation_model)
    ap.add_argument("--prompt-version", default=Settings().prompt_version, choices=sorted(PROMPTS))
    ap.add_argument("--json", action="store_true", help="사람이 읽는 출력 대신 결과 전체를 JSON 으로")
    ap.add_argument("--debug", action="store_true", help="오류를 한 줄로 줄이지 않고 전체 트레이스백을 본다")
    args = ap.parse_args(argv)
    settings = Settings(generation_model=args.model, prompt_version=args.prompt_version)
    try:
        result = answer_question(args.question, build_pipeline(settings), settings,
                                 load_key("ANTHROPIC_API_KEY", settings.env_path))
    except (RuntimeError, OSError, ValueError) as e:
        if args.debug:
            raise
        print(f"오류: {error_text(e)}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=1) if args.json else format_result(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
