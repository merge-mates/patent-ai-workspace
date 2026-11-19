"""PreToolUse 훅: report 정답 폴더(data/goldsets/report/)를 Claude 도구로 여는 것을 막는다.

settings.json의 Read(...) 금지는 Read 도구만 막는다. 이 훅은 Bash(cat, head, rg, grep,
python 등)와 Read·Grep·Glob 입력의 글자를 보고 막는다. 채점기는 설정(config)의
`goldset: report`로 폴더를 고르므로 명령 글자에 그 경로가 안 나와 막히지 않는다.

한계: 글자로만 본다. 변수·따옴표로 쪼갠 경로, 폴더를 도는 스크립트 파일은 못 잡는다.
실수로 여는 것을 막는 안전띠이지 샌드박스가 아니다.

입력: stdin JSON (tool_name, tool_input). exit 2 = 막고 이유를 Claude에게 돌려줌.
"""

import json
import re
import shlex
import sys

# data/goldsets/ 아래에서 열어도 되는 것 (tune 세트, VERSION 파일). 나머지는 다 막는다.
ALLOWED_AFTER_GOLDSETS = re.compile(r"goldsets/(tune|VERSION)(?=$|[/\s\"'`;&|)])")

# 셸·파이썬 와일드카드 글자
GLOB_CHARS = re.compile(r"[*?\[{]")

# data 폴더 자체 또는 지금 폴더·위 폴더 (그 아래를 통째로 도는 명령이 report까지 읽음)
DATA_OR_ROOT = re.compile(r"^(?:.*/)?data/?$|^\.{1,2}/?$")


def mentions_report(text: str) -> bool:
    """글자 안에 report 정답 폴더(또는 그것을 가릴 수 없는 goldsets 경로)가 있는지."""
    for m in re.finditer(r"goldsets", text):
        if not ALLOWED_AFTER_GOLDSETS.match(text, m.start()):
            return True  # goldsets 폴더 자체, report, 와일드카드 등
    # data/gold* 같은 와일드카드로 goldsets를 가리키는 경우
    for token in re.split(r"[\s\"'`;&|()]+", text):
        if "gold" in token.lower() and GLOB_CHARS.search(token):
            return True
    return False


def recursive_over_data(command: str) -> bool:
    """data 폴더(또는 지금 폴더) 전체를 도는 명령인지. 그러면 report 파일도 읽힌다."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    names = [t.rsplit("/", 1)[-1] for t in tokens]
    targets = [t for t in tokens if DATA_OR_ROOT.match(t)]

    # grep -r / -R / --recursive
    if "grep" in names and any(
        t in ("--recursive", "--dereference-recursive")
        or re.fullmatch(r"-[a-zA-Z]*[rR][a-zA-Z]*", t)
        for t in tokens
    ):
        return bool(targets)
    # rg는 .gitignore(/data)를 따라 data를 건너뛴다. 무시를 끄면 막는다.
    if "rg" in names and any(
        t in ("--no-ignore", "-u", "-uu", "-uuu", "--follow", "-L") for t in tokens
    ):
        return True
    # 폴더째 복사·묶기·실행
    if any(n in ("tar", "zip", "rsync", "cp", "find", "tree", "du") for n in names) or (
        "ls" in names and any(re.fullmatch(r"-[a-zA-Z]*R[a-zA-Z]*", t) for t in tokens)
    ):
        return any(DATA_OR_ROOT.match(t) and not re.fullmatch(r"\.{1,2}/?", t) for t in tokens)
    return False


def texts_to_check(tool_name: str, tool_input: dict) -> list[str]:
    """도구별로 경로가 들어가는 칸을 모은다."""
    keys = {
        "Bash": ["command"],
        "Read": ["file_path"],
        "Grep": ["path", "glob"],  # pattern은 찾을 글자라 경로가 아니다
        "Glob": ["path", "pattern"],
    }.get(tool_name, [])
    return [str(tool_input.get(k, "")) for k in keys if tool_input.get(k)]


def main() -> int:
    try:
        data = json.load(sys.stdin)
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input") or {}
    except Exception:  # JSON이 아니거나 모양이 다르면
        # 입력을 못 읽으면 조용히 통과시키지 않는다
        print("report 정답 막기 훅이 입력을 읽지 못해 막았다.", file=sys.stderr)
        return 2

    texts = texts_to_check(tool_name, tool_input)

    if any(mentions_report(t) for t in texts):
        print(
            "data/goldsets/report/(봉인된 report 정답)는 Claude가 열지 않는다. "
            "채점기(eval/run_eval.py)만 설정의 goldset: report로 읽는다. "
            "tune 세트는 data/goldsets/tune/ 경로를 그대로 쓴다.",
            file=sys.stderr,
        )
        return 2
    if tool_name == "Bash" and recursive_over_data(texts[0] if texts else ""):
        print(
            "data 폴더(또는 지금 폴더) 전체를 도는 명령은 report 정답까지 읽어서 막았다. "
            "data/goldsets/tune/ 같은 아래 폴더를 직접 지정한다.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
