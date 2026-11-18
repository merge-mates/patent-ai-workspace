"""특허·실용신안 심사기준 판별 첨부파일(본문 PDF, 없으면 HWP) 받기.

- data/raw/body_특허실용신안_심사기준_<ID>_<시행일>.json 8개의 '첨부파일' 목록을 읽는다.
- 판마다 심사기준 본문 파일 하나만 고른다
  (이름에 '개정이유서'·'제개정이유서'·'설명자료'가 있으면 본문 아님).
  본문 후보 중 PDF 를 먼저, 없으면 HWP.
- 이미 data/raw/exam_guideline_<flSeq>.pdf 가 있으면 새로 받지 않고, 서버 파일 크기(HEAD 요청)와
  기존 파일 크기를 비교해 '기존 파일과 같음'으로 기록한다.
- 저장: data/raw/exam_guideline_versions/<ID>_<시행일>.<확장자> (이미 있으면 멈춤)
- 기록: data/raw/exam_guideline_versions/_download_log_1118.json
- 첨부 링크(flDownload.do)에는 인증키가 들어가지 않는다. 호출 사이 1초 쉰다.

실행: python scripts/fetch_exam_guideline_attachments.py
"""

import glob
import json
import re
import sys
import time
from pathlib import Path

import requests

RAW_DIR = Path("data/raw")
OUT_DIR = RAW_DIR / "exam_guideline_versions"
LOG_PATH = OUT_DIR / "_download_log_1118.json"
NOT_BODY = ("개정이유서", "설명자료")  # 이 말이 들어간 첨부는 본문이 아님

OUT_DIR.mkdir(parents=True, exist_ok=True)
if LOG_PATH.exists():
    sys.exit(f"이미 있는 파일이라 멈춥니다: {LOG_PATH}")


def as_list(x):
    return x if isinstance(x, list) else ([x] if x else [])


log = []
for f in sorted(glob.glob(str(RAW_DIR / "body_특허실용신안_심사기준_*.json"))):
    rid, efyd = re.search(r"_(\d{13})_(\d{8})\.json$", f).groups()
    svc = json.loads(Path(f).read_text(encoding="utf-8"))["AdmRulService"]
    info = svc["행정규칙기본정보"]
    att = svc.get("첨부파일") or {}
    pairs = list(
        zip(as_list(att.get("첨부파일명")), as_list(att.get("첨부파일링크")), strict=False)
    )
    body = [(n, lk) for n, lk in pairs if not any(w in n for w in NOT_BODY)]
    # 본문 후보: PDF 먼저, 없으면 HWP
    pick = [p for p in body if p[0].lower().endswith(".pdf")] or [
        p for p in body if p[0].lower().endswith((".hwp", ".hwpx"))
    ]
    row = {
        "행정규칙일련번호": rid,
        "시행일자": efyd,
        "발령번호": info.get("발령번호"),
        "발령기관": info.get("소관부처명"),
        "첨부파일_전체": [n for n, _ in pairs],
    }
    if not pick:
        row.update(status="fail: 본문 첨부를 못 고름")
        log.append(row)
        print(rid, "본문 첨부를 못 고름", [n for n, _ in pairs])
        continue
    name, link = pick[0]  # 같은 본문 PDF 가 둘이면(제101호) 첫 번째
    seq = link.rsplit("=", 1)[-1]
    ext = Path(name).suffix.lower()
    row.update(
        선택_첨부=name, flSeq=seq, link=link, 안받은_첨부=[n for n, lk in pairs if lk != link]
    )

    old = RAW_DIR / f"exam_guideline_{seq}{ext}"
    if old.exists():
        time.sleep(1)
        head = requests.head(link, timeout=60, allow_redirects=True)
        remote = head.headers.get("Content-Length")
        same = remote is not None and int(remote) == old.stat().st_size
        row.update(
            path=str(old),
            bytes=old.stat().st_size,
            remote_bytes=remote,
            status="기존 파일과 같음(새로 안 받음)"
            if same
            else (
                "기존 파일 있음, 크기 확인 못 함(새로 안 받음)"
                if remote is None
                else "기존 파일 있음, 크기 다름(새로 안 받음)"
            ),
        )
        log.append(row)
        print(rid, row["status"], old)
        continue

    out = OUT_DIR / f"{rid}_{efyd}{ext}"
    if out.exists():
        sys.exit(f"이미 있는 파일이라 멈춥니다: {out}")
    time.sleep(1)
    try:
        resp = requests.get(link, timeout=300, allow_redirects=True)
    except requests.RequestException as e:
        row.update(status=f"fail: 요청 오류 {type(e).__name__}")
        log.append(row)
        continue
    content = resp.content
    magic = content[:8]
    # 파일 앞머리로 형식 확인: PDF=%PDF, HWP(옛 형식)=OLE D0CF11E0, HWPX=zip PK
    ok_magic = (
        (magic[:4] == b"%PDF")
        if ext == ".pdf"
        else (magic[:4] in (b"\xd0\xcf\x11\xe0", b"PK\x03\x04"))
    )
    if resp.status_code != 200 or not ok_magic:
        row.update(
            status=f"fail: HTTP {resp.status_code}, 앞머리 {magic!r}",
            bytes=len(content),
            content_type=resp.headers.get("Content-Type"),
        )
        log.append(row)
        print(rid, row["status"])
        continue
    out.write_bytes(content)
    row.update(path=str(out), bytes=len(content), status="ok")
    log.append(row)
    print(f"{rid} 저장 {out} ({len(content):,} bytes) <- {name}")

LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
print("기록:", LOG_PATH)
