"""현행 특허법·시행령·시행규칙 본문 받기 + JSON 구조 확인.

- scripts/list_patent_laws.py 가 저장한 목록에서 '현행' 판의 MST/시행일을 읽음
- 본문조회: lawService.do (target=eflaw, MST, efYd, type=JSON)  <- type=JSON 은 가정
- 원본은 data/raw/body_<이름>_<MST>_<시행일>.json 으로 저장 (판본 구분용 파일명)
- 필드 이름을 가정하지 않고 키 구조만 출력

실행: python scripts/fetch_law_body.py
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

URL = "https://www.law.go.kr/DRF/lawService.do"
RAW_DIR = Path("data/raw")
TARGETS = ["특허법", "특허법 시행령", "특허법 시행규칙"]


def pick_current(name: str) -> dict:
    path = RAW_DIR / f"list_{name.replace(' ', '_')}.json"
    laws = json.loads(path.read_text(encoding="utf-8"))["LawSearch"]["law"]
    cur = [l for l in laws if l.get("법령명한글", "").strip() == name
           and l.get("현행연혁코드") == "현행"]
    if len(cur) != 1:
        sys.exit(f"'{name}' 현행 판이 {len(cur)}개입니다. 목록을 확인하세요.")
    return cur[0]


def outline(node, depth=0, max_depth=3, key="root"):
    pad = "  " * depth
    if isinstance(node, dict):
        print(f"{pad}{key}: dict({len(node)})")
        if depth < max_depth:
            for k, v in node.items():
                outline(v, depth + 1, max_depth, k)
    elif isinstance(node, list):
        print(f"{pad}{key}: list({len(node)})")
        if node and depth < max_depth:
            outline(node[0], depth + 1, max_depth, key + "[0]")
    else:
        s = str(node).replace("\n", " ")
        print(f"{pad}{key}: {s[:40]}")


for name in TARGETS:
    law = pick_current(name)
    mst, efyd = law["법령일련번호"], law["시행일자"]
    params = {"OC": OC, "target": "eflaw", "MST": mst, "efYd": efyd, "type": "JSON"}
    resp = requests.get(URL, params=params, timeout=60)
    print(f"\n=== {name} MST={mst} 시행일={efyd} status={resp.status_code} "
          f"content-type={resp.headers.get('Content-Type')}")
    resp.raise_for_status()
    try:
        data = resp.json()
    except ValueError:
        print("JSON 이 아닙니다. 응답 앞부분:\n", resp.text[:500].replace(OC, "***"))
        continue
    out = RAW_DIR / f"body_{name.replace(' ', '_')}_{mst}_{efyd}.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2).replace(OC, "***"), encoding="utf-8")
    print(f"저장: {out} ({out.stat().st_size:,} bytes)")
    if name == "특허법":  # 구조는 특허법만 출력
        outline(data)
