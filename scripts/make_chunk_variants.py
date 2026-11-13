"""변수 실험용 변형 청크 파일 만들기 (새 파일로만 저장, 덮어쓰지 않음).

  python scripts/make_chunk_variants.py --variant noheader
V1 noheader: 각 청크 첫 줄(조문 번호·제목 이름표)을 뺀 본문만.
V5 context: 장·절·관 제목을 청크 맨 앞에 붙임(Phase 6 실험 ③).
V2 notags 는 청커로 만든다: python -m src.law_api.chunker data/raw/body_특허법_279827_20251111.json --strip-tags
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.retrieval.variants import make_context, make_noheader  # noqa: E402

SRC = Path("data/processed/chunks_특허법_279827_20251111.jsonl")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True, choices=["noheader", "context"])
    ap.add_argument("--src", type=Path, default=SRC)
    args = ap.parse_args(argv)
    chunks = [json.loads(l) for l in args.src.read_text(encoding="utf-8").splitlines() if l.strip()]
    out = args.src.with_name(f"{args.src.stem}_{args.variant}.jsonl")
    if out.exists():
        sys.exit(f"이미 있는 파일이라 덮어쓰지 않습니다: {out}")
    rows = make_noheader(chunks) if args.variant == "noheader" else make_context(chunks)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    lens = sorted(len(r["text"]) for r in rows)
    print(f"청크 {len(rows)}개, 본문 길이 중앙값 {lens[len(lens)//2]}, 최대 {lens[-1]} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
