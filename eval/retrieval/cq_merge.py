"""CQ 후보 파일 모으기 (design.md 7-5).

사용: uv run python -m eval.retrieval.cq_merge <파일>... -o <출력>
모든 파일에 있는 row_id만 남긴다 (교집합). 정답 세트 버전·해시가 다르면 멈춘다.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from eval.retrieval.checks import _is_git_ignored
from eval.retrieval.errors import RetrievalEvalError

logger = logging.getLogger(__name__)
SAME_FIELDS = ("goldset_version", "gold_sha256")  # 파일끼리 같아야 하는 칸


def _read(path: Path) -> list[dict]:
    try:
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    except (OSError, ValueError) as e:
        # 내용 글자가 섞일 수 있어 종류만 적는다
        raise RetrievalEvalError(f"CQ 파일을 못 읽는다: {path.name} ({type(e).__name__})") from None


def merge_cq(paths: list[str | Path]) -> list[dict]:
    """파일들의 교집합 줄을 첫 파일 순서대로 돌려준다. 버전·해시가 다르면 RetrievalEvalError."""
    if not paths:
        raise RetrievalEvalError("CQ 파일이 0개다")
    files = [(Path(p), _read(Path(p))) for p in paths]
    # 다른 정답으로 만든 파일은 섞지 않는다
    base_name, base = files[0]
    for name, rows in files[1:]:
        for field in SAME_FIELDS:
            a = {r.get(field) for r in base}
            b = {r.get(field) for r in rows}
            if len(a | b) > 1:
                raise RetrievalEvalError(f"{field}이(가) 다르다: {base_name.name}, {name.name}")
    common = set.intersection(*({r["row_id"] for r in rows} for _, rows in files))
    merged = [r for r in base if r["row_id"] in common]
    if not merged:
        logger.warning("CQ 교집합이 0건이다 (파일 %d개)", len(files))
    return merged


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="eval.retrieval.cq_merge")
    ap.add_argument("files", nargs="*")
    ap.add_argument("-o", "--output", required=True)
    args = ap.parse_args(argv)
    out = Path(args.output)
    try:
        # 모은 파일에도 질의가 있으니 git에 들어갈 수 있는 곳이면 멈춘다
        if not _is_git_ignored(out):
            raise RetrievalEvalError("출력이 git에 들어갈 수 있는 경로다 (저장소 밖만)")
        if len(args.files) == 1:
            _read(Path(args.files[0]))  # 읽히는지만 본다
            text = Path(args.files[0]).read_text(encoding="utf-8")
        else:
            merged = merge_cq(args.files)
            text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in merged)
    except RetrievalEvalError as e:
        print(f"CQ 모으기 실패: {e}", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"저장: {len(text.splitlines())}줄", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
