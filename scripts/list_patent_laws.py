"""특허법·시행령·시행규칙 후보 목록 확인 (본문은 아직 받지 않음).

- 현행법령 목록(eflaw)에서 검색 -> 원본 JSON을 data/raw 에 저장
- 법령명이 정확히 일치하는 항목만 출력 (판본별로 여러 줄 나옴)
가정(확인 필요): display(한 페이지 개수), page 파라미터

실행: python scripts/list_patent_laws.py
"""
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
OC = os.getenv("LAW_OC")
if not OC:
    sys.exit(".env 에 LAW_OC 값이 없습니다.")

URL = "https://www.law.go.kr/DRF/lawSearch.do"
TARGETS = ["특허법", "특허법 시행령", "특허법 시행규칙"]
RAW_DIR = Path("data/raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)

for name in TARGETS:
    params = {"OC": OC, "target": "eflaw", "type": "JSON",
              "query": name, "display": 100, "page": 1}
    resp = requests.get(URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    out = RAW_DIR / f"list_{name.replace(' ', '_')}.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2).replace(OC, "***"), encoding="utf-8")

    body = data.get("LawSearch", {})
    laws = body.get("law", [])
    if isinstance(laws, dict):  # 1건이면 dict 로 올 수 있음
        laws = [laws]
    print(f"\n=== '{name}' 검색: 응답 {len(laws)}건 (totalCnt={body.get('totalCnt')}) -> {out}")
    for law in laws:
        if law.get("법령명한글", "").strip() == name:
            print(f"  [{law.get('현행연혁코드')}] MST={law.get('법령일련번호')} "
                  f"시행일={law.get('시행일자')} 공포일={law.get('공포일자')} "
                  f"{law.get('제개정구분명')}")
