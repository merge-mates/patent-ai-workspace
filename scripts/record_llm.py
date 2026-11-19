"""사람이 돌려 진짜 모델 답을 녹화 파일로 저장한다 (테스트용 녹화 만들기).

사용: uv run python scripts/record_llm.py <단계> <변수 JSON 파일> [--out 폴더]
- 진짜 모델 API를 부른다(비용 발생). 키는 환경 변수에서 SDK가 읽고, 출력·저장하지 않는다.
- 이미 같은 녹화가 있으면 멈춘다 (덮어쓰지 않음).
- 지어낸 통지서만 녹화한다. 저장소 data/ 아래 변수 파일은 거부한다.
- 녹화를 tests/fixtures로 옮기는 일은 사람이 한다.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from patent_ai.core.llm.config import REPO_ROOT, load_step_config
from patent_ai.core.llm.prompts import render_prompt
from patent_ai.core.llm.recorded import recording_key, save_recording

# 기본 녹화 위치: git 밖 work/
DEFAULT_OUT = REPO_ROOT / "work" / "llm_recordings"


def repo_roots(git_common_dir: str | None = None) -> list[Path]:
    """data/ 를 검사할 저장소 루트들: 이 worktree와 메인 checkout(git 공통 폴더의 부모)."""
    roots = [REPO_ROOT]
    if git_common_dir is None:
        try:
            out = subprocess.run(
                ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            git_common_dir = out.stdout.strip()
        except OSError, subprocess.CalledProcessError:
            git_common_dir = None
    if git_common_dir:
        roots.append(Path(git_common_dir).parent)
    return roots


def is_under_data_dir(path: Path, roots: list[Path] | None = None) -> bool:
    """경로가 어느 루트의 data/ 아래로 풀리면 True.

    .. 와 심볼릭 링크는 풀고, 대소문자는 가리지 않는다 (맥은 DATA/ 도 같은 폴더).
    """
    target = Path(str(Path(path).resolve()).casefold())
    for root in roots if roots is not None else repo_roots():
        data = Path(str((Path(root) / "data").resolve()).casefold())
        if target.is_relative_to(data):
            return True
    return False


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
