"""채점 명령 하나: 실험 설정의 `feature:` 칸을 보고 기능 채점기를 부른다 (#20, #101 댓글 2번).

명령: uv run python eval/run_eval.py --config experiments/<실험>/config.yaml [채점기 인자...]
--config 말고 받은 인자는 고른 채점기에 그대로 넘긴다 (예: 검색의 --chunks).
"""

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    # `python eval/run_eval.py`로 파일을 직접 돌리면 저장소 뿌리가 import 경로에 없다
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml  # noqa: E402

from eval.f1.score import main as f1_main  # noqa: E402
from eval.f4.score import main as f4_main  # noqa: E402
from eval.retrieval.score import main as retrieval_main  # noqa: E402

# feature 이름 -> 채점기 main(argv) -> 종료 코드
SCORERS = {
    "f1": f1_main,
    "f4": f4_main,
    "retrieval": retrieval_main,
}


def _feature(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"설정 파일이 없다: {path.name}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        raise ValueError(f"설정 파일 YAML 문법이 틀리다: {path.name}") from None
    if not isinstance(data, dict):
        raise ValueError(f"설정 파일이 비었거나 모양이 틀리다: {path.name}")
    feature = data.get("feature")
    if not isinstance(feature, str):
        raise ValueError(f"설정에 feature 칸이 없다 (고를 수 있는 값: {', '.join(SCORERS)})")
    if feature not in SCORERS:
        raise ValueError(f"모르는 feature: {feature} (고를 수 있는 값: {', '.join(SCORERS)})")
    return feature


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="eval/run_eval.py")
    ap.add_argument("--config", required=True)
    args, rest = ap.parse_known_args(argv)
    try:
        feature = _feature(Path(args.config))
    except ValueError as e:
        print(f"채점 실패: {e}", file=sys.stderr)
        return 1
    return SCORERS[feature](["--config", args.config, *rest])


if __name__ == "__main__":
    raise SystemExit(main())
