"""특허·실용신안 심사기준 옛 판 본문 받기 (지정한 행정규칙일련번호만).

- 방식은 scripts/fetch_exam_guidelines_body.py(이 PR에 없음, 은진 로컬 feat/law-chunker)와 같다:
  lawService.do (target=admrul, ID=<행정규칙일련번호>, type=JSON)
- 저장: data/raw/body_특허실용신안_심사기준_<ID>_<시행일>.json
- 이미 있는 파일은 덮어쓰지 않고 멈춘다. 저장 파일 안의 인증키는 *** 로 가린다.
- 호출 사이 1초 쉰다.

실행: python scripts/fetch_exam_guidelines_versions.py
"""

import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
OC = os.getenv("LAW_OC")
if not OC:
    sys.exit(".env 에 LAW_OC 값이 없습니다.")

URL = "https://www.law.go.kr/DRF/lawService.do"
RAW_DIR = Path("data/raw")

# (행정규칙일련번호, 시행일자) — 받을 옛 판 목록
VERSIONS = [
    ("2100000143152", "20180801"),
    ("2100000176778", "20190318"),
    ("2100000186000", "20200101"),
    ("2100000191985", "20200810"),
    ("2100000195891", "20201214"),
]

# 시작 전에 이미 있는 파일이 하나라도 있으면 아무것도 받지 않고 멈춘다
for rid, efyd in VERSIONS:
    out = RAW_DIR / f"body_특허실용신안_심사기준_{rid}_{efyd}.json"
    if out.exists():
        sys.exit(f"이미 있는 파일이라 멈춥니다: {out}")

for i, (rid, efyd) in enumerate(VERSIONS):
    if i:
        time.sleep(1)
    out = RAW_DIR / f"body_특허실용신안_심사기준_{rid}_{efyd}.json"
    params = {"OC": OC, "target": "admrul", "ID": rid, "type": "JSON"}
    try:
        resp = requests.get(URL, params=params, timeout=120)
    except requests.RequestException as e:
        print(f"실패 {rid}: 요청 오류 {type(e).__name__}")
        continue
    print(
        f"{rid} status={resp.status_code} content-type={resp.headers.get('Content-Type')} "
        f"크기={len(resp.content):,} bytes"
    )
    if resp.status_code != 200:
        print(f"실패 {rid}: HTTP {resp.status_code}")
        continue
    try:
        data = resp.json()
    except ValueError:
        # JSON 이 아니면 저장하지 않고 앞부분만 보여준다(키는 가림)
        print(f"실패 {rid}: JSON 아님. 앞부분: {resp.text[:300].replace(OC, '***')!r}")
        continue
    info = (
        data.get("AdmRulService", {}).get("행정규칙기본정보", {}) if isinstance(data, dict) else {}
    )
    out.write_text(
        json.dumps(data, ensure_ascii=False, indent=2).replace(OC, "***"), encoding="utf-8"
    )
    print(
        f"저장: {out} (최상위 키={list(data)[:3]}, 시행일자={info.get('시행일자')}, "
        f"발령번호={info.get('발령번호')})"
    )
