"""사람이 돌려 진짜 모델 답을 녹화 파일로 저장한다 (테스트용 녹화 만들기).

사용: uv run python scripts/record_llm.py <단계> <변수 JSON 파일> [--out 폴더]
- 진짜 모델 API를 부른다(비용 발생). 키는 환경 변수에서 SDK가 읽고, 출력·저장하지 않는다.
- 이미 같은 녹화가 있으면 멈춘다 (덮어쓰지 않음).
"""

import argparse
import json
import sys
from pathlib import Path

from patent_ai.core.llm.config import REPO_ROOT, load_step_config
from patent_ai.core.llm.prompts import render_prompt
from patent_ai.core.llm.recorded import recording_key, save_recording


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("step", help="<기능>.<단계> 예: f1.extract")
    ap.add_argument("variables_file", type=Path, help="프롬프트 변수 JSON 파일")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "tests" / "fixtures" / "llm_recordings")
    args = ap.parse_args(argv)

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
