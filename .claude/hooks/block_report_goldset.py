"""PreToolUse 훅: report 정답 폴더(data/goldsets/report/)를 Claude 도구로 여는 것을 막는다.

settings.json의 Read(...) 금지는 Read 도구만 막는다. 이 훅은 Bash(cat, head, rg, grep,
python 등)와 Read·Grep·Glob·Write·Edit 입력의 경로 글자를 보고 막는다. 채점기는 설정(config)의
`goldset: report`로 폴더를 고르므로 명령 글자에 그 경로가 안 나와 막히지 않는다.

막는 것은 둘이다.
1. 경로가 report 폴더(또는 그 위 goldsets 폴더 자체)를 가리킨다. `..`은 정리하고,
   와일드카드는 그 폴더에 맞을 수 있으면 막는다. 대소문자는 가리지 않는다 (macOS 디스크).
2. 폴더째 읽는 명령(grep -r, rg, find -exec, tar, cp -r 등)이 data 폴더나 그 위를 대상으로 한다.
검색어(grep·rg의 패턴)·커밋 메시지·echo 글자는 경로가 아니라서 보지 않는다.

한계: 글자로만 본다. 변수로 만든 경로, 폴더를 도는 스크립트 파일은 못 잡는다.
실수로 여는 것을 막는 안전띠이지 샌드박스가 아니다.

입력: stdin JSON (tool_name, tool_input, cwd). exit 2 = 막고 이유를 Claude에게 돌려줌.
어떤 예외가 나도 exit 2로 막는다 (조용히 통과시키지 않는다).
"""

import fnmatch
import json
import os
import posixpath
import re
import shlex
import sys

# data/goldsets/ 아래에서 열어도 되는 것
ALLOWED_UNDER_GOLDSETS = {"tune", "version"}
GLOB_CHARS = re.compile(r"[*?\[{]")
# 토큰 안에서 경로처럼 보이는 조각을 떼어 낼 때 자르는 글자 (python -c 코드 안의 경로 등)
SPLIT_CHARS = re.compile(r"[\s'\"`(),;:<>|&$=]+")
INTERPRETERS = {"python", "python3", "sh", "bash", "zsh", "node", "perl", "ruby"}

# 결과 종류
REPORT = "report"  # report 폴더 또는 goldsets 폴더 자체를 가리킴 → 늘 막음
DATA = "data"  # data 폴더 자체 → 폴더째 읽는 명령이면 막음
ABOVE = "above"  # data의 위 폴더 (저장소 루트 등) → .gitignore를 안 따르는 폴더째 명령이면 막음


class Blocked(Exception):
    """막을 이유."""


def comps(path: str) -> list[str]:
    return [c for c in path.lower().split("/") if c not in ("", ".")]


def match_prefix(pattern: list[str], target: list[str], deep_from: int) -> bool:
    """pattern 경로 조각들이 target 앞부분에 맞을 수 있는지.

    `**`는 data 폴더 아래(deep_from 자리부터)에서만 아무 깊이로 본다. 그 위에서는 `*` 하나로 본다
    (`**/*.py`처럼 저장소 전체를 보는 흔한 패턴까지 막지 않으려고).
    """
    for i, p in enumerate(pattern):
        if p == "**":
            if i >= deep_from:
                return True
            p = "*"
        if i >= len(target):
            return True  # target 끝(report)보다 깊이 들어감 → report 안
        if not fnmatch.fnmatchcase(target[i], p):
            return False
    return True


def classify(path: str, base: str, data_dirs: list[str]) -> str | None:
    """경로 하나가 report·data·그 위 중 어디를 가리킬 수 있는지."""
    if not path:
        return None
    full = posixpath.normpath(posixpath.join(base, path))
    pc = comps(full)
    best = None
    for data_dir in data_dirs:
        dc = comps(data_dir)
        target = dc + ["goldsets", "report"]
        if not match_prefix(pc, target, len(dc)):
            continue
        if len(pc) >= len(dc) + 1:  # goldsets 폴더 자체이거나 더 깊음
            return REPORT
        if len(pc) == len(dc):
            best = DATA
        elif best is None:
            best = ABOVE
    # 다른 저장소·worktree를 거친 경로: 어디든 .../goldsets 다음이 tune·VERSION이 아니면 막음
    for i, c in enumerate(pc):
        if fnmatch.fnmatchcase("goldsets", c) and i > 0 and fnmatch.fnmatchcase("data", pc[i - 1]):
            rest = pc[i + 1 :]
            if not rest or rest[0] == "**" or fnmatch.fnmatchcase("report", rest[0]):
                return REPORT
        if c == "goldsets" and "/" in path:
            rest = pc[i + 1 :]
            if not rest or (rest[0] not in ALLOWED_UNDER_GOLDSETS):
                return REPORT
    return best


def pieces(token: str) -> list[str]:
    """토큰 안의 경로 조각들 (python -c 코드 안의 'data/...' 같은 것)."""
    return [p for p in SPLIT_CHARS.split(token) if p]


def split_heredocs(command: str) -> tuple[str, list[tuple[str, str]]]:
    """heredoc 본문을 떼어 낸다. (본문 뺀 명령, [(그 heredoc이 붙은 줄, 본문)])."""
    lines = command.split("\n")
    out, docs, i = [], [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", line)
        i += 1
        if m:
            body = []
            while i < len(lines) and lines[i].strip() != m.group(1):
                body.append(lines[i])
                i += 1
            i += 1  # 끝 표시 줄
            docs.append((line, "\n".join(body)))
    return "\n".join(out), docs


def segments(command: str) -> list[list[str]]:
    """; && || | 줄바꿈으로 나눈 명령 조각들 (각각 글자 목록)."""
    lex = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()")
    lex.whitespace_split = True
    lex.commenters = ""
    segs: list[list[str]] = [[]]
    cur = segs[0]
    for tok in lex:
        if tok and set(tok) <= set(";&|()"):
            cur = []
            segs.append(cur)
        else:
            cur.append(tok)
    return [s for s in segs if s]


# 값을 하나 받는 옵션 중 그 값이 경로가 아닌 것 (검색어·메시지·필터)
NON_PATH_VALUE_OPTS = {
    "-e", "--regexp", "-m", "--message", "--grep", "-S", "-G", "--author",
    "-g", "--glob", "--iglob", "-t", "--type", "-T", "--type-not", "--include", "--exclude",
    "-A", "-B", "-C", "--max-count", "-M", "-j", "--threads", "-n",
}  # fmt: skip
SEARCHERS = {"grep", "egrep", "fgrep", "rg", "ag"}


def path_args(argv: list[str]) -> list[str]:
    """명령 글자 중 경로 자리만 고른다. 검색어·메시지·echo 글자는 뺀다."""
    if not argv:
        return []
    name = argv[0].rsplit("/", 1)[-1]
    if name in ("echo", "printf"):
        return []
    args = argv[1:]
    is_git = name == "git"
    searcher = name in SEARCHERS or (is_git and args[:1] == ["grep"])
    if is_git and args[:1] == ["commit"]:
        return []  # 커밋 메시지
    has_pattern_opt = any(a in ("-e", "--regexp", "-f", "--file") for a in args)
    out, skip_next, pattern_taken = [], False, has_pattern_opt
    for a in args:
        if skip_next:
            skip_next = False
            continue
        if a.startswith("-"):
            if "=" in a:
                opt, val = a.split("=", 1)
                if opt not in NON_PATH_VALUE_OPTS:
                    out.append(val)
            elif a in NON_PATH_VALUE_OPTS and not (a == "-n" and not is_git):
                skip_next = True
            continue
        if searcher and not pattern_taken and not (is_git and a == "grep"):
            pattern_taken = True  # 첫 자리 = 검색어
            continue
        out.append(a)
    return out


def short_flags(argv: list[str]) -> str:
    return "".join(a[1:] for a in argv[1:] if re.fullmatch(r"-[a-zA-Z]+", a))


def check_recursive(argv: list[str], targets: list[str], base, data_dirs) -> None:
    """폴더째 읽는 명령이 data(또는 그 위)를 대상으로 하면 막는다."""
    name = argv[0].rsplit("/", 1)[-1]
    flags = short_flags(argv)
    longs = {a.split("=", 1)[0] for a in argv[1:] if a.startswith("--")}

    def kinds(default_cwd: bool) -> set:
        ts = targets or (["."] if default_cwd else [])
        return {classify(t, base, data_dirs) for t in ts}

    msg = "data 폴더(또는 그 위 폴더) 전체를 읽는 명령은 report 정답까지 읽는다"
    if name in ("grep", "egrep", "fgrep"):
        if "r" in flags or "R" in flags or longs & {"--recursive", "--dereference-recursive"}:
            if kinds(True) & {DATA, ABOVE}:
                raise Blocked(msg + " (grep은 .gitignore를 모른다)")
    elif name in ("rg", "ag"):
        if any(x.startswith("--no-ignore") or x == "--unrestricted" for x in longs) or "u" in flags:
            raise Blocked("rg의 무시 끄기(--no-ignore*, -u)는 data 폴더까지 읽는다")
        if kinds(True) & {DATA}:
            raise Blocked("rg에 data 폴더를 직접 주면 .gitignore와 상관없이 그 안을 읽는다")
    elif name == "find":
        reads = any(a in ("-exec", "-execdir", "-ok", "-okdir") for a in argv)
        if reads and kinds(True) & {DATA, ABOVE}:
            raise Blocked(msg + " (find -exec)")
        if kinds(True) & {DATA}:
            raise Blocked("data 폴더 안 파일 목록에는 report 정답 이름이 나온다")
    elif name in ("tar", "zip", "rsync", "cp", "scp"):
        recursive = name in ("tar", "rsync") or "r" in flags or "R" in flags or "a" in flags
        recursive = recursive or bool(longs & {"--recursive", "--archive"})
        if recursive and kinds(False) & {DATA, ABOVE}:
            raise Blocked(msg + f" ({name})")
    elif name in ("ls", "tree"):
        if (name != "ls" or "R" in flags or "--recursive" in longs) and kinds(True) & {DATA}:
            raise Blocked("data 폴더 안 파일 목록에는 report 정답 이름이 나온다")
    elif name == "xargs":
        # find ... | xargs cat 처럼 앞 명령의 목록을 읽는 경우는 check_bash가 본다
        pass


def check_paths(texts: list[str], base: str, data_dirs: list[str]) -> None:
    for t in texts:
        for p in pieces(t):
            if classify(p, base, data_dirs) == REPORT:
                raise Blocked(f"경로 '{p}'가 report 정답 폴더를 가리킨다")


def check_bash(command: str, cwd: str, data_dirs: list[str]) -> None:
    body_free, docs = split_heredocs(command)
    for line, body in docs:
        first = line.strip().split()
        names = {w.rsplit("/", 1)[-1] for w in first[:3]}
        if names & INTERPRETERS:
            check_paths([body], cwd, data_dirs)  # 인터프리터에 넘기는 코드
    base = cwd
    segs = segments(body_free)
    for k, argv in enumerate(segs):
        # 앞의 env·uv run 같은 앞붙이를 건너뛴다
        while argv and (re.fullmatch(r"\w+=.*", argv[0]) or argv[0] in ("env", "sudo", "time")):
            argv = argv[1:]
        if argv[:2] == ["uv", "run"]:
            argv = argv[2:]
        if not argv:
            continue
        targets = path_args(argv)
        check_paths(targets, base, data_dirs)
        check_recursive(argv, targets, base, data_dirs)
        name = argv[0].rsplit("/", 1)[-1]
        if name == "xargs" and k > 0 and segs[k - 1][:1] == ["find"]:
            prev = path_args(segs[k - 1]) or ["."]
            if {classify(t, base, data_dirs) for t in prev} & {DATA, ABOVE}:
                raise Blocked("find 목록을 xargs로 읽으면 report 정답까지 읽는다")
        if name in ("cd", "pushd") and targets:
            base = posixpath.normpath(posixpath.join(base, targets[0]))


def check(data: dict) -> None:
    tool = data["tool_name"]
    inp = data["tool_input"]
    if not isinstance(inp, dict):
        raise TypeError("tool_input이 객체가 아니다")
    cwd = data.get("cwd") or os.getcwd()
    project = os.environ.get("CLAUDE_PROJECT_DIR") or cwd
    data_dir = posixpath.join(project, "data")
    data_dirs = [data_dir]
    real = os.path.realpath(data_dir)  # worktree면 data가 원래 폴더로 가는 링크
    if real != data_dir:
        data_dirs.append(real)

    if tool == "Bash":
        check_bash(str(inp.get("command", "")), cwd, data_dirs)
    elif tool in ("Read", "Write", "Edit", "MultiEdit", "NotebookEdit"):
        # 읽기뿐 아니라 덮어쓰기·고치기도 막는다 (내용 칸은 보지 않고 경로 칸만)
        path = inp.get("file_path") or inp.get("notebook_path") or ""
        check_paths([str(path)], cwd, data_dirs)
    elif tool in ("Grep", "Glob"):
        path = str(inp.get("path") or "")
        if tool == "Glob":
            pattern = str(inp.get("pattern", ""))
            full = posixpath.join(path, pattern) if path else pattern
            if classify(full, cwd, data_dirs) == REPORT:
                raise Blocked("Glob 패턴이 report 정답 폴더에 맞을 수 있다")
        if path:
            kind = classify(path, cwd, data_dirs)
            if kind in (REPORT, DATA):
                raise Blocked(f"{tool}에 data 폴더를 주면 report 정답까지 본다")


def main() -> int:
    try:
        check(json.load(sys.stdin))
    except Blocked as e:
        print(
            f"막음: {e}. data/goldsets/report/(봉인된 report 정답)는 Claude가 열지 않는다. "
            "채점기(eval/run_eval.py)만 설정의 goldset: report로 읽는다. "
            "tune 세트는 data/goldsets/tune/처럼 아래 폴더를 직접 지정한다.",
            file=sys.stderr,
        )
        return 2
    except Exception as e:  # 어떤 예외든 조용히 통과시키지 않는다
        print(f"report 정답 막기 훅이 입력을 처리하지 못해 막았다: {e!r}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
