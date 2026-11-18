"""사람이 돌려 진짜 모델 답을 녹화 파일로 저장한다 (테스트용 녹화 만들기).

사용: uv run python scripts/record_llm.py <단계> <변수 JSON 파일> [--out 폴더]
- 진짜 모델 API를 부른다(비용 발생). 키는 환경 변수에서 SDK가 읽고, 출력·저장하지 않는다.
- 이미 같은 녹화가 있으면 멈춘다 (덮어쓰지 않음).
- 지어낸 통지서만 녹화한다. 저장소 data/ 아래 변수 파일은 거부한다.
- 녹화를 tests/fixtures로 옮기는 일은 사람이 한다.
"""

import argparse
import json
import sys
from pathlib import Path

from patent_ai.core.llm.config import REPO_ROOT, load_step_config
from patent_ai.core.llm.prompts import render_prompt
from patent_ai.core.llm.recorded import recording_key, save_recording

# 기본 녹화 위치: git 밖 work/
DEFAULT_OUT = REPO_ROOT / "work" / "llm_recordings"


def is_under_data_dir(path: Path, repo_root: Path = REPO_ROOT) -> bool:
    """경로가 저장소 data/ 아래로 풀리면 True (.. 와 심볼릭 링크는 풀어서 본다)."""
    resolved = Path(path).resolve()
    return resolved.is_relative_to((Path(repo_root) / "data").resolve())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("step", help="<기능>.<단계> 예: f1.extract")
    ap.add_argument("variables_file", type=Path, help="프롬프트 변수 JSON 파일")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    # 비공개 자료(data/)가 외부 모델로 가지 않게 먼저 막는다
    if is_under_data_dir(args.variables_file):
        print(f"data/ 아래 파일은 녹화에 쓸 수 없음: {args.variables_file}", file=sys.stderr)
        return 1

    cfg = load_step_config(args.step)
    variables = json.loads(args.variables_file.read_text(encoding="utf-8"))
    prompt = render_prompt(cfg.prompt, variables, REPO_ROOT)

    # 이미 있으면 진짜 호출 전에 멈춘다
    key = recording_key(
        step=args.step,
        model=cfg.model,
        prompt=prompt,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
    )
    if (args.out / f"{key}.json").exists():
        print(f"이미 녹화가 있어 멈춤: {args.out / f'{key}.json'}", file=sys.stderr)
        return 1

    print(f"진짜 모델 API를 부릅니다 (비용 발생): 단계={args.step}, 모델={cfg.model}")
    if input("계속하려면 yes 입력: ").strip() != "yes":
        print("취소")
        return 1

    from patent_ai.core.llm.transport import AnthropicTransport

    resp = AnthropicTransport().complete(
        step=args.step,
        model=cfg.model,
        prompt=prompt,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
    )
    path = save_recording(
        args.out,
        resp,
        step=args.step,
        model=cfg.model,
        prompt=prompt,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
    )
    print(f"저장: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
