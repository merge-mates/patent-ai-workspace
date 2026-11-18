#!/usr/bin/env bash
# 진행 보드 칸을 저절로 옮기는 훅 (PostToolUse, Bash).
# - 이슈 브랜치를 만들면 (git switch -c / git checkout -b <type>/<이슈번호>-…) → 그 이슈 "In Progress"
# - PR을 만들면 (gh pr create) → 지금 브랜치 이름의 이슈 "In Review"
# - 머지되면 "Done"은 GitHub 보드 규칙이 한다 (PR 본문 Closes #N → 이슈 닫힘 → Done).
# 칸을 못 옮겨도 작업은 막지 않는다. 대신 이유를 Claude에게 돌려줘서 사람에게 알리게 한다.
input=$(cat)
cmd=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' <<<"$input" 2>/dev/null)
[[ -z "$cmd" ]] && exit 0
# 브랜치는 훅 입력의 cwd(세션이 일하는 폴더) 기준으로 구한다.
# 훅 프로세스의 현재 폴더는 $CLAUDE_PROJECT_DIR(메인 체크아웃)이라, worktree 세션이면 엉뚱한 브랜치가 나온다.
cwd=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("cwd",""))' <<<"$input" 2>/dev/null)
[[ -d "$cwd" ]] || cwd="$PWD"

dir="$(cd "$(dirname "$0")/.." && pwd)"
move() { # <이슈번호> <칸>
  local out
  out=$("$dir/scripts/board-status.sh" "$1" "$2" 2>&1)
  local rc=$?
  [[ $rc -ne 0 ]] && out="$out (보드를 손으로 옮기거나 위 이유를 고친 뒤 .claude/scripts/board-status.sh $1 \"$2\")"
  python3 -c 'import json,sys; print(json.dumps({"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":sys.argv[1]}}, ensure_ascii=False))' "$out"
}
issue_of() { [[ "$1" =~ ^[a-z]+/([0-9]+)- ]] && echo "${BASH_REMATCH[1]}"; }

if [[ "$cmd" =~ git[[:space:]]+(switch[[:space:]]+(-c|-C|--create)|checkout[[:space:]]+-[bB])[[:space:]]+([^[:space:];&|]+) ]]; then
  branch="${BASH_REMATCH[3]}"
  [[ "$(git -C "$cwd" branch --show-current 2>/dev/null)" == "$branch" ]] || exit 0   # 브랜치가 실제로 생겼을 때만
  n=$(issue_of "$branch")
  [[ -n "$n" ]] && move "$n" "In Progress"
  exit 0
fi

if [[ "$cmd" =~ gh[[:space:]]+pr[[:space:]]+create ]]; then
  branch=$(git -C "$cwd" branch --show-current 2>/dev/null)
  n=$(issue_of "$branch")
  [[ -z "$n" ]] && exit 0
  (cd "$cwd" && gh pr view "$branch" --json number >/dev/null 2>&1) || exit 0   # PR이 실제로 생겼을 때만 (그 폴더의 저장소에서)
  move "$n" "In Review"
fi
exit 0
