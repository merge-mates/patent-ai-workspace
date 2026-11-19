"""experiments/index.md(실험 점수 표)를 다시 만든다. 손으로 고치지 않는다 (.claude/rules/eval.md).

명령: uv run python eval/make_index.py
읽는 것: experiments/<실험>/card.md 머리(--- 사이)와 scores.json.
_template처럼 _로 시작하는 폴더는 뺀다.
같은 입력이면 늘 같은 글자를 쓴다 (실험 이름 순서).
"""

import argparse
import json
import logging
import sys
from pathlib import Path

if __package__ in (None, ""):
    # `python eval/make_index.py`로 파일을 직접 돌리면 저장소 뿌리가 import 경로에 없다
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.common.errors import EvalError  # noqa: E402
from eval.common.paths import REPO_ROOT  # noqa: E402

logger = logging.getLogger(__name__)

HEAD = (
    "<!-- eval/make_index.py가 만든다. 손으로 고치지 않는다. -->\n"
    "# 실험 점수 표\n"
    "| 실험 | 기능 | 바꾼 것 | 주 지표 | 기준선 대비 | 비용 | 카드 |\n"
    "|---|---|---|---|---|---|---|\n"
)
# 카드 머리에 꼭 있어야 하는 칸 (experiments/_template/card.md)
REQUIRED = ("기능", "기준선", "바꾼 것", "주 지표")


def read_card_head(card: Path) -> dict[str, str]:
    """card.md 맨 위 --- 사이의 `이름: 값` 줄을 읽는다. 값에 ':'가 있어도 첫 ': '로만 나눈다."""
    lines = card.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---" or "---" not in [x.strip() for x in lines[1:]]:
        raise EvalError(f"{card.parent.name}: card.md 머리(--- 사이)가 없다")
    head: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, _, value = line.partition(":")
            head[key.strip()] = value.strip()
    missing = [k for k in REQUIRED if not head.get(k)]
    if missing:
        raise EvalError(f"{card.parent.name}: card.md 머리 칸이 빠졌다: {', '.join(missing)}")
    return head


def _baseline_name(value: str) -> str:
    # "experiments/m1-i2-f1-baseline/" -> "m1-i2-f1-baseline"
    return Path(value.strip().rstrip("/")).name


def _scores(exp_dir: Path) -> dict | None:
    p = exp_dir / "scores.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise EvalError(f"{exp_dir.name}: scores.json JSON 문법이 틀리다") from None


def _primary(name: str, scores: dict, metric: str) -> float:
    value = (scores.get("metrics") or {}).get(metric)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise EvalError(f"{name}: 주 지표 {metric}가 scores.json metrics에 없다")
    return float(value)


def build_index(experiments_dir: str | Path) -> str:
    root = Path(experiments_dir)
    dirs = sorted(d for d in root.iterdir() if d.is_dir() and not d.name.startswith("_"))
    if not dirs:
        logger.warning("실험이 0개다 (표 머리만 쓴다)")
        return HEAD

    cards: dict[str, dict[str, str]] = {}
    for d in dirs:
        card = d / "card.md"
        if not card.is_file():
            raise EvalError(f"{d.name}: card.md가 없다")
        cards[d.name] = read_card_head(card)

    rows = []
    for d in dirs:
        head = cards[d.name]
        metric = head["주 지표"]
        scores = _scores(d)
        if scores is None:
            logger.warning("%s: scores.json이 없다 (점수 없음 줄)", d.name)
            rows.append(
                f"| {d.name} | {head['기능']} | {head['바꾼 것']} | 점수 없음 | - | - "
                f"| [card]({d.name}/card.md) |"
            )
            continue
        value = _primary(d.name, scores, metric)
        base = _baseline_name(head["기준선"])
        if base == d.name:
            diff = "기준선"
        else:
            # 기준선 점수가 없거나 그 지표가 없으면 비교하지 않는다
            base_scores = _scores(root / base) if (root / base).is_dir() else None
            base_value = ((base_scores or {}).get("metrics") or {}).get(metric)
            diff = "-" if not isinstance(base_value, int | float) else f"{value - base_value:+.3f}"
        usd = (scores.get("cost") or {}).get("usd")
        cost = f"${usd:.2f}" if isinstance(usd, int | float) else "-"
        rows.append(
            f"| {d.name} | {head['기능']} | {head['바꾼 것']} | {metric} {value:.3f} | {diff} "
            f"| {cost} | [card]({d.name}/card.md) |"
        )
    return HEAD + "".join(r + "\n" for r in rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="eval/make_index.py")
    ap.add_argument("--experiments-dir", default=str(REPO_ROOT / "experiments"))
    ap.add_argument("--out", default=None, help="기본: <experiments-dir>/index.md")
    args = ap.parse_args(argv)
    root = Path(args.experiments_dir)
    out = Path(args.out) if args.out else root / "index.md"
    try:
        text = build_index(root)
    except EvalError as e:
        print(f"목록 만들기 실패: {e}", file=sys.stderr)
        return 1
    out.write_text(text, encoding="utf-8")
    print(f"{out.name} 저장: 실험 {text.count(chr(10)) - HEAD.count(chr(10))}개", file=sys.stderr)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    raise SystemExit(main())
