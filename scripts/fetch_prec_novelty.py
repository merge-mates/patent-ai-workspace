"""신규성 판례 본문 받기 (법제처 Open API, target=prec).

방법 (data/raw/DOWNLOAD_1116.md 1절과 같음)
- 목록: lawSearch.do?target=prec&type=JSON&search=2(본문검색)&query=<검색어>
  &org=<법원>&display=100&sort=ddes
  - org=400201(대법원), 400202(하위법원). 모든 쪽(page)을 다 받는다.
- 고르기: 사건종류명=특허 만. 대법원 최대 10건 먼저, 남은 자리는 특허법원으로 채워 최대 15건.
  각 법원 안에서는 사건명이 '거절결정'으로 시작하는 사건을 앞에, 그 다음 나머지. 둘 다 최신순.
  이미 data/raw/prec 에 같은 사건번호 본문이 있으면 받지 않고 '중복'으로 기록(15건 수에는 안 셈).
- 본문: lawService.do?target=prec&type=JSON&ID=<판례일련번호>
- 저장: data/raw/prec/body_<사건번호>_<판례일련번호>.json
  목록 원본은 list_신규성_대법원.json / list_신규성_하위법원.json
- 기록: data/raw/prec/_download_log_1118.json (기존 _download_log_1116.json 과 같은 칸)

원칙: 기존 파일은 덮어쓰지 않는다. 인증키는 저장 파일에서 *** 로 가린다. 호출 사이 1초 쉰다.
실행: python scripts/fetch_prec_novelty.py
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

SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"
PREC_DIR = Path("data/raw/prec")
QUERY = "특허법 제29조 제1항"
TOPIC = "신규성"
MAX_TOTAL, MAX_SUPREME = 15, 10
LOG_PATH = PREC_DIR / "_download_log_1118.json"
LIST_PATHS = {
    "400201": PREC_DIR / f"list_{TOPIC}_대법원.json",
    "400202": PREC_DIR / f"list_{TOPIC}_하위법원.json",
}


def mask(text: str) -> str:
    return text.replace(OC, "***")


def get(url, params, timeout=60):
    time.sleep(1)  # 호출 사이 1초 쉬기
    return requests.get(url, params=params, timeout=timeout)


def search_all(org: str) -> dict:
    """한 법원의 검색 결과를 모든 쪽에 걸쳐 모아 하나의 목록으로 만든다."""
    items, page, first = [], 1, None
    while True:
        params = {
            "OC": OC,
            "target": "prec",
            "type": "JSON",
            "search": 2,
            "query": QUERY,
            "org": org,
            "display": 100,
            "page": page,
            "sort": "ddes",
        }
        resp = get(SEARCH_URL, params)
        if resp.status_code != 200:
            # raise_for_status()는 인증키가 든 URL을 찍으므로 상태 코드만 보인다
            sys.exit(f"목록 요청 실패 org={org} page={page}: HTTP {resp.status_code}")
        body = resp.json()["PrecSearch"]
        first = first or {k: v for k, v in body.items() if k != "prec"}
        got = body.get("prec", [])
        if isinstance(got, dict):
            got = [got]
        items += got
        total = int(body.get("totalCnt") or 0)
        if not got or len(items) >= total:
            break
        page += 1
    first["prec"] = items
    first["page"] = f"1-{page}"
    return {"PrecSearch": first}


# 이미 받아 둔 사건번호(파일명 body_<사건번호>_<일련번호>.json 에서 읽음)
existing = {}
for p in PREC_DIR.glob("body_*.json"):
    m = re.match(r"body_(.+)_(\d+)\.json$", p.name)
    if m:
        existing[m.group(1)] = p

for path in [LOG_PATH, *LIST_PATHS.values()]:
    if path.exists():
        sys.exit(f"이미 있는 파일이라 멈춥니다: {path}")

lists = {}
for org, path in LIST_PATHS.items():
    data = search_all(org)
    path.write_text(mask(json.dumps(data, ensure_ascii=False, indent=2)), encoding="utf-8")
    lists[org] = data["PrecSearch"]["prec"]
    print(
        f"목록 org={org}: totalCnt={data['PrecSearch'].get('totalCnt')}, "
        f"받은 {len(lists[org])}건 -> {path}"
    )


def pick(items, court_name):
    """특허 사건만, 법원명 일치, 거절결정 먼저 + 최신순으로 정렬."""
    rows = [i for i in items if i.get("사건종류명") == "특허" and i.get("법원명") == court_name]
    rows.sort(key=lambda i: i.get("선고일자", ""), reverse=True)
    rej = [i for i in rows if i.get("사건명", "").startswith("거절결정")]
    return rej + [i for i in rows if i not in rej]


supreme = pick(lists["400201"], "대법원")
lower = pick(lists["400202"], "특허법원")
print(f"특허 사건: 대법원 {len(supreme)}건, 특허법원 {len(lower)}건")

log, n_new, n_supreme = [], 0, 0
seen = set()
for court, rows in (("대법원", supreme), ("특허법원", lower)):
    for item in rows:
        if n_new >= MAX_TOTAL or (court == "대법원" and n_supreme >= MAX_SUPREME):
            break
        no, sid = item["사건번호"], item["판례일련번호"]
        if no in seen:
            continue
        seen.add(no)
        row = {
            "topic": TOPIC,
            "사건번호": no,
            "판례일련번호": sid,
            "법원명": item.get("법원명"),
            "선고일자": item.get("선고일자"),
            "사건명": item.get("사건명"),
        }
        if no in existing:
            row.update(path=str(existing[no]), status="dup", bytes=None)
            log.append(row)
            print(f"중복 {no} ({existing[no].name})")
            continue
        out = PREC_DIR / f"body_{no}_{sid}.json"
        row["path"] = str(out)
        try:
            resp = get(
                SERVICE_URL, {"OC": OC, "target": "prec", "type": "JSON", "ID": sid}, timeout=120
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
            # JSON 이 아니면 저장하지 않고 앞부분을 기록(키는 가림)
            row.update(status="fail: JSON 아님", bytes=None, head=mask(resp.text[:200]))
            log.append(row)
            print(f"실패 {no}: JSON 아님")
            continue
        svc = data.get("PrecService") if isinstance(data, dict) else None
        if not svc or not (svc.get("판례내용") or "").strip():
            row.update(status="fail: 본문(판례내용) 비어 있음", bytes=None, keys=list(data)[:5])
            log.append(row)
            print(f"실패 {no}: 본문 비어 있음")
            continue
        text = mask(json.dumps(data, ensure_ascii=False, indent=2))
        out.write_text(text, encoding="utf-8")
        row.update(status="ok", bytes=out.stat().st_size)
        log.append(row)
        n_new += 1
        if court == "대법원":
            n_supreme += 1
        print(
            f"저장 {no} {item.get('선고일자')} {item.get('사건명')} "
            f"-> {out} ({row['bytes']:,} bytes)"
        )

LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"새로 받은 {n_new}건(대법원 {n_supreme}), 기록 {len(log)}줄 -> {LOG_PATH}")
