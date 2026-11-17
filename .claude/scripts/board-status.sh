#!/usr/bin/env bash
# 진행 보드(이 저장소에 연결된 GitHub 프로젝트)에서 이슈 카드의 Status 칸을 옮긴다.
# 쓰는 법: .claude/scripts/board-status.sh <이슈번호> "<칸 이름>"
#   칸 이름 예: "Todo" "In Progress" "In Review" "Done" (보드의 Status 옵션 이름 그대로)
# 보드 번호, Status 필드 id, 옵션 id는 적어 두지 않고 매번 gh로 찾는다 (보드를 다시 만들어도 그대로 돈다).
# 필요: gh 로그인 + project 권한 (`gh auth refresh -s project`, 사람마다 한 번).
# 실패하면 이유를 stderr에 쓰고 0이 아닌 값으로 끝난다 (조용히 성공하지 않는다).
set -uo pipefail

issue="${1:-}"
want="${2:-}"
if [[ ! "$issue" =~ ^[0-9]+$ || -z "$want" ]]; then
  echo "쓰는 법: $0 <이슈번호> \"<칸 이름>\"" >&2
  exit 64
fi

if ! scopes=$(gh auth status 2>&1); then
  echo "보드: gh 로그인이 안 되어 있다. 'gh auth login' 뒤 다시." >&2
  exit 1
fi
if ! grep -q "'project'" <<<"$scopes"; then
  echo "보드: gh에 project 권한이 없다. 터미널에서 'gh auth refresh -s project'를 한 번 한다." >&2
  exit 1
fi

repo=$(gh repo view --json nameWithOwner -q .nameWithOwner) || { echo "보드: 저장소를 찾지 못했다." >&2; exit 1; }
owner="${repo%%/*}"
name="${repo##*/}"

# 저장소에 연결된 프로젝트, 그 Status 필드·옵션, 이 이슈의 카드를 한 번에 가져온다.
json=$(gh api graphql -F owner="$owner" -F name="$name" -F n="$issue" -f query='
query($owner:String!, $name:String!, $n:Int!) {
  repository(owner:$owner, name:$name) {
    projectsV2(first: 10) {
      nodes {
        id number title closed
        field(name: "Status") {
          ... on ProjectV2SingleSelectField { id options { id name } }
        }
      }
    }
    issue(number: $n) {
      id state
      projectItems(first: 20) { nodes { id project { id } } }
    }
  }
}') || { echo "보드: GitHub 조회 실패 (이슈 #$issue)." >&2; exit 1; }

read -r -d '' pick <<'PY'
import json, sys
want, title = sys.argv[1], sys.argv[2]
d = json.load(sys.stdin)["data"]["repository"]
issue = d.get("issue")
if not issue:
    print("ERR\x1f이슈가 없다 (PR 번호이거나 다른 저장소 번호일 수 있다)"); sys.exit()
projects = [p for p in d["projectsV2"]["nodes"] if not p["closed"] and p.get("field")]
if title:
    projects = [p for p in projects if p["title"] == title]
if not projects:
    print("ERR\x1f저장소에 연결된 보드(Status 칸이 있는 프로젝트)가 없다"); sys.exit()
p = projects[0]
warn = f"보드가 {len(projects)}개라 '{p['title']}'를 썼다. 고르려면 BOARD_PROJECT_TITLE을 준다" if len(projects) > 1 else ""
opts = {o["name"]: o["id"] for o in p["field"]["options"]}
if want not in opts:
    print("ERR\x1f보드에 '%s' 칸이 없다. 있는 칸: %s" % (want, ", ".join(opts))); sys.exit()
item = next((i["id"] for i in issue["projectItems"]["nodes"] if i["project"]["id"] == p["id"]), "")
print("\x1f".join(["OK", p["id"], str(p["number"]), p["title"], p["field"]["id"], opts[want], issue["id"], item, warn]))
PY
plan=$(python3 -c "$pick" "$want" "${BOARD_PROJECT_TITLE:-}" <<<"$json" 2>/dev/null)
IFS=$'\x1f' read -r status pid pnum ptitle fid oid iid item warn <<<"$plan"
if [[ "$status" != "OK" ]]; then
  echo "보드: #$issue 옮기지 못함 — ${pid:-GitHub 응답을 읽지 못했다}" >&2
  exit 1
fi
[[ -n "${warn:-}" ]] && echo "보드: $warn" >&2

# 카드가 아직 없으면 보드에 붙인다.
if [[ -z "${item:-}" ]]; then
  item=$(gh api graphql -f pid="$pid" -f cid="$iid" -f query='
mutation($pid:ID!, $cid:ID!) { addProjectV2ItemById(input:{projectId:$pid, contentId:$cid}) { item { id } } }' \
    -q .data.addProjectV2ItemById.item.id) || { echo "보드: #$issue 카드를 보드에 붙이지 못했다." >&2; exit 1; }
fi

if ! gh api graphql -f pid="$pid" -f item="$item" -f fid="$fid" -f oid="$oid" -f query='
mutation($pid:ID!, $item:ID!, $fid:ID!, $oid:String!) {
  updateProjectV2ItemFieldValue(input:{projectId:$pid, itemId:$item, fieldId:$fid, value:{singleSelectOptionId:$oid}}) { projectV2Item { id } }
}' >/dev/null; then
  echo "보드: #$issue를 '$want'로 옮기지 못했다." >&2
  exit 1
fi
echo "보드: #$issue → $want ($ptitle #$pnum)"
