"""신규성 판례 다시 채우기: 본문에 '제29조 제1항'이 실제로 나오는 특허 사건만 15건이 되게.

- 1차 기록 data/raw/prec/_download_log_1118.json 의 각 줄에 '본문_제29조제1항'(Y/N) 칸을 더한다.
  N 인 건은 파일은 그대로 두고 '신규성 아님(진보성 등)' 또는 '상표 사건'으로 표시만 한다.
- 1차 때 저장한 검색 목록(list_신규성_대법원.json / list_신규성_하위법원.json)에서
  아직 안 본 사건을 이어서 본다.
  순서: 대법원 거절결정 → 특허법원 거절결정 → 대법원 나머지 → 특허법원 나머지 (각각 최신순).
  사건종류명=특허 이면서 사건명에 (상)·(디)·(실)이 붙은 상표·디자인·실용신안 사건은 뺀다.
- 본문을 받아 '제29조 제1항'(또는 '29조 1항')이 판시사항·판결요지·참조조문·판례내용에
  나오면 저장(Y),
  안 나오면 저장하지 않고 'N(확인만, 저장 안 함)'으로 기록한다.
  새로 받은 Y 건이 1차 Y 건과 합쳐 15건이 되면 멈춘다.
- 이미 data/raw/prec 에 본문이 있는 사건은 받지 않고 '중복'으로 기록(수에 안 셈).
- 기록: data/raw/prec/_download_log_1118_v2.json (새 파일)
- 원칙: 기존 파일은 덮어쓰지 않는다. 인증키는 저장 파일에서 *** 로 가린다. 호출 사이 1초 쉰다.

실행: python scripts/fetch_prec_novelty_refill.py
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
OC = os.getenv("LAW_OC")
if not OC:
    sys.exit(".env 에 LAW_OC 값이 없습니다.")

SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"
PREC_DIR = Path("data/raw/prec")
LOG1 = PREC_DIR / "_download_log_1118.json"
LOG2 = PREC_DIR / "_download_log_1118_v2.json"
TARGET_Y = 15
# '제29조 제1항', '제29조제1항', '29조 1항' 등을 잡는다. 앞에 숫자가 붙은 '제129조 제1항'은 뺀다
PAT = re.compile(r"(?<!\d)29조\s*제?\s*1항")
EXCLUDE_MARK = ("(상)", "(디)", "(실)")

if LOG2.exists():
    sys.exit(f"이미 있는 파일이라 멈춥니다: {LOG2}")


def count_29_1(svc: dict) -> int:
    text = " ".join(str(svc.get(k) or "") for k in ("판시사항", "판결요지", "참조조문", "판례내용"))
    return len(PAT.findall(text))


def label_n(name: str) -> str:
    return "상표 사건" if "(상)" in (name or "") else "신규성 아님(진보성 등)"


# 1) 1차 기록에 Y/N 칸 더하기
log = json.loads(LOG1.read_text(encoding="utf-8"))
n_y = 0
for row in log:
    row["round"] = "1차"
    svc = json.loads(Path(row["path"]).read_text(encoding="utf-8"))["PrecService"]
    cnt = count_29_1(svc)
    row["본문_제29조제1항"] = "Y" if cnt else "N"
    row["제29조제1항_횟수"] = cnt
    if not cnt:
        row["표시"] = label_n(row.get("사건명"))
    if row["status"] == "ok" and cnt:
        n_y += 1
print(f"1차: 새로 받은 {sum(r['status'] == 'ok' for r in log)}건 중 Y {n_y}건")

# 2) 검색 목록에서 다음 사건 이어서 보기
seen = {r["사건번호"] for r in log}
existing = {}
for p in PREC_DIR.glob("body_*.json"):
    m = re.match(r"body_(.+)_(\d+)\.json$", p.name)
    if m:
        existing[m.group(1)] = p


def load_list(name):
    items = json.loads((PREC_DIR / name).read_text(encoding="utf-8"))["PrecSearch"]["prec"]
    return items if isinstance(items, list) else [items]


def ordered(items, court):
    rows = [
        i
        for i in items
        if i.get("사건종류명") == "특허"
        and i.get("법원명") == court
        and not any(m in (i.get("사건명") or "") for m in EXCLUDE_MARK)
    ]
    rows.sort(key=lambda i: i.get("선고일자", ""), reverse=True)
    rej = [i for i in rows if (i.get("사건명") or "").startswith("거절결정")]
    rest = [i for i in rows if i not in rej]
    return rej, rest


s_rej, s_rest = ordered(load_list("list_신규성_대법원.json"), "대법원")
l_rej, l_rest = ordered(load_list("list_신규성_하위법원.json"), "특허법원")
queue = s_rej + l_rej + s_rest + l_rest

for item in queue:
    if n_y >= TARGET_Y:
        break
    no, sid = item["사건번호"], item["판례일련번호"]
    if no in seen:
        continue
    seen.add(no)
    row = {
        "topic": "신규성",
        "사건번호": no,
        "판례일련번호": sid,
        "법원명": item.get("법원명"),
        "선고일자": item.get("선고일자"),
        "사건명": item.get("사건명"),
        "round": "다시 채우기",
    }
    if no in existing:
        svc = json.loads(existing[no].read_text(encoding="utf-8"))["PrecService"]
        cnt = count_29_1(svc)
        row.update(
            path=str(existing[no]),
            status="dup",
            bytes=None,
            본문_제29조제1항="Y" if cnt else "N",
            제29조제1항_횟수=cnt,
        )
        log.append(row)
        print(f"중복 {no} ({'Y' if cnt else 'N'})")
        continue
    time.sleep(1)  # 호출 사이 1초 쉬기
    try:
        resp = requests.get(
            SERVICE_URL, params={"OC": OC, "target": "prec", "type": "JSON", "ID": sid}, timeout=120
        )
    except requests.RequestException as e:
        row.update(status=f"fail: 요청 오류 {type(e).__name__}", bytes=None)
        log.append(row)
        continue
    if resp.status_code != 200:
        row.update(status=f"fail: HTTP {resp.status_code}", bytes=None)
        log.append(row)
        continue
    try:
        data = resp.json()
    except ValueError:
        row.update(status="fail: JSON 아님", bytes=None, head=resp.text[:200].replace(OC, "***"))
        log.append(row)
        print(f"실패 {no}: JSON 아님")
        continue
    svc = data.get("PrecService") if isinstance(data, dict) else None
    if not svc or not (svc.get("판례내용") or "").strip():
        row.update(status="fail: 본문(판례내용) 비어 있음", bytes=None)
        log.append(row)
        print(f"실패 {no}: 본문 비어 있음")
        continue
    cnt = count_29_1(svc)
    row.update(본문_제29조제1항="Y" if cnt else "N", 제29조제1항_횟수=cnt)
    if not cnt:
        # 신규성과 관계없는 사건은 저장하지 않는다
        row.update(status="N(확인만, 저장 안 함)", path=None, bytes=None)
        log.append(row)
        print(f"N {no} {item.get('사건명')}")
        continue
    out = PREC_DIR / f"body_{no}_{sid}.json"
    if out.exists():
        sys.exit(f"이미 있는 파일이라 멈춥니다: {out}")
    out.write_text(
        json.dumps(data, ensure_ascii=False, indent=2).replace(OC, "***"), encoding="utf-8"
    )
    row.update(status="ok", path=str(out), bytes=out.stat().st_size)
    log.append(row)
    n_y += 1
    print(f"저장 Y {no} {item.get('선고일자')} {item.get('사건명')} ({cnt}회) -> {out}")

LOG2.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Y 합계 {n_y}건 (목표 {TARGET_Y}), 기록 {len(log)}줄 -> {LOG2}")
