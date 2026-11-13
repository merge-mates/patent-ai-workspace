"""청킹 단위 비교용 코퍼스 만들기(Phase 6 실험 ①).

  python scripts/make_unit_corpora.py corpora          # 조문 단위 3개 법령 + 혼합(조문+항) 코퍼스 jsonl 생성
  python scripts/make_unit_corpora.py merge-emb --article-emb <조문 임베딩> --paragraph-emb <항 임베딩>   # 혼합용 임베딩 합치기

- 조문 단위: 특허법·시행령·시행규칙의 조문 청크 파일을 이어 붙인다(502개). 항 단위는 기존 `chunks_법령3_paragraph_split3000.jsonl`.
- 혼합: 조문 청크 502개 + 항 청크를 한 파일에(순서: 조문 먼저). 항이 없는 조문 179개는 항 코퍼스에도 조문 전체가 같은 id·같은 글로 들어 있어 중복이라 빼므로 항 청크는 1,152개(합 1,654개).
  같은 조문의 조문·항 청크는 채점·결합 단계에서 조문으로 묶인다.
결과는 data/processed/ 에 새 파일로만 저장(덮어쓰지 않음).
"""
import argparse
import json
import sys
from pathlib import Path

P = Path("data/processed")
ARTICLE_SOURCES = [P / "chunks_특허법_279827_20251111.jsonl",
                   P / "chunks_특허법_시행령_277553_20251001.jsonl",
                   P / "chunks_특허법_시행규칙_286191_20260514.jsonl"]
PARAGRAPH = P / "chunks_법령3_paragraph_split3000.jsonl"
ARTICLE_OUT = P / "chunks_법령3_article.jsonl"
MIXED_OUT = P / "chunks_법령3_mixed.jsonl"


def read_lines(path: Path) -> list[str]:
    return [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def write_new(path: Path, lines: list[str]) -> None:
    if path.exists():
        sys.exit(f"이미 있는 파일이라 덮어쓰지 않습니다: {path}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"저장: {path} ({len(lines)}개)")


def make_corpora() -> None:
    article = [l for src in ARTICLE_SOURCES for l in read_lines(src)]
    paragraph = read_lines(PARAGRAPH)
    article_ids = {json.loads(l)["chunk_id"]: l for l in article}
    paragraph_only = []
    for l in paragraph:
        cid = json.loads(l)["chunk_id"]
        if cid in article_ids:  # 항이 없는 조문: 조문 청크와 같은 글이어야 한다
            if json.loads(article_ids[cid])["text"] != json.loads(l)["text"]:
                sys.exit(f"같은 id 인데 글이 다릅니다: {cid}")
        else:
            paragraph_only.append(l)
    all_ids = list(article_ids) + [json.loads(l)["chunk_id"] for l in paragraph_only]
    if len(all_ids) != len(set(all_ids)):
        sys.exit("청크 id 가 겹칩니다.")
    write_new(ARTICLE_OUT, article)
    write_new(MIXED_OUT, article + paragraph_only)


def merge_emb(article_emb: Path, paragraph_emb: Path) -> None:
    a, p = (json.loads(x.read_text(encoding="utf-8")) for x in (article_emb, paragraph_emb))
    if a["meta"]["model"] != p["meta"]["model"]:
        sys.exit("두 임베딩의 모델이 다릅니다.")
    expected = [json.loads(l)["chunk_id"] for l in read_lines(MIXED_OUT)]
    a_set = set(a["ids"])
    keep = [i for i, cid in enumerate(p["ids"]) if cid not in a_set]
    ids = a["ids"] + [p["ids"][i] for i in keep]
    if ids != expected:
        sys.exit("합친 id 순서가 혼합 코퍼스와 다릅니다.")
    out = P / f"emb_{a['meta']['model']}_chunks-law3-mixed_merged.json"
    if out.exists():
        sys.exit(f"이미 있는 파일이라 덮어쓰지 않습니다: {out}")
    meta = {**a["meta"], "n": len(ids), "tag": "law3-mixed", "source": f"merge of {article_emb.name} + {paragraph_emb.name}"}
    out.write_text(json.dumps({"meta": meta, "ids": ids, "vectors": a["vectors"] + [p["vectors"][i] for i in keep]}), encoding="utf-8")
    print(f"저장: {out} ({len(ids)}개)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("corpora")
    m = sub.add_parser("merge-emb")
    m.add_argument("--article-emb", type=Path, required=True)
    m.add_argument("--paragraph-emb", type=Path, required=True)
    args = ap.parse_args(argv)
    if args.cmd == "corpora":
        make_corpora()
    else:
        merge_emb(args.article_emb, args.paragraph_emb)
    return 0


if __name__ == "__main__":
    sys.exit(main())
