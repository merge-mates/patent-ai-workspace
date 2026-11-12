#!/usr/bin/env bash
# 리뷰·확인 에이전트의 Bash를 읽기 전용 명령으로 묶는다.
# 에이전트 정의의 hooks에서 PreToolUse(Bash)로 불림. 입력은 stdin JSON (tool_input.command).
# exit 2 = 막고 이유를 Claude에게 돌려줌 (Claude Code 공식 문서 Hooks).
cmd=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))')

# 막을 것: 작업 트리·HEAD·브랜치를 바꾸는 git, 파일 쓰기·지우기
if echo "$cmd" | grep -Eq '\bgit\s+(checkout|switch|restore|reset|stash|commit|merge|rebase|push|pull|cherry-pick|revert|clean|branch\s+-[dDmM]|tag)\b'; then
  echo "읽기 전용 에이전트는 git 상태를 바꾸는 명령을 쓸 수 없다: $cmd. 옛 내용은 git show <커밋>:<파일>로 본다." >&2
  exit 2
fi
# 2>/dev/null, >/dev/null 같은 버리기는 허용한다
chk=$(printf '%s' "$cmd" | sed -E 's#[0-9]?>>?[[:space:]]*/dev/null##g; s#[0-9]?>&[0-9]##g')
if echo "$chk" | grep -Eq '(^|[;&|]\s*)(rm|mv|cp|touch|mkdir|tee)\b|>\s*[^&]|\bsed\s+-i\b'; then
  echo "읽기 전용 에이전트는 파일을 만들거나 고칠 수 없다: $cmd" >&2
  exit 2
fi
exit 0
