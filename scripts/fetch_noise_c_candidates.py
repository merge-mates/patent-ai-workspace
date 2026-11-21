"""C안 노이즈 후보 받기 (이슈 #178 T2, KIPRIS Plus 공보 검색).

한 번 쓰는 받기 스크립트다 (CLAUDE.md 코드 규칙 예외: 캐시·호출 상한 모듈을 거치지 않는다).
대신 이미 받은 파일이면 그 OA는 부르지 않고, 호출 사이를 쉬고, 키를 출력·저장하지 않는다.

- 입력: 질의 표 <goldsets_root>/tune/retrieval/cite_c_queries.yaml {발송번호: {ipc, words}}
  (초안: `uv run python -m eval.retrieval.noise_c --draft-queries --ipc-csv <사건 목록 CSV>`)
- 호출: OA마다 1번. 같은 IPC + 청구항 낱말로 공개·등록공보를 찾는다 (특허만, 실용신안 뺌).
  우선일·같은 특허 거르기는 받은 뒤 eval/retrieval/noise_c.py가 한다. 넉넉히 받으려고 --rows건.
- 저장: work/kipris_c/<발송번호>.xml (git 밖, 응답 그대로)
- 키: .env의 KIPRIS_PLUS_API_KEY (Open API 무료 옵션, 월 1,000건. 30 OA면 30건)

확인 안 된 것: 오퍼레이션(getAdvancedSearch)과 칸 이름(ipcNumber·claimScope)·낱말 잇는 꼴은
KIPRIS Plus 안내 화면 기준이고 이 저장소에서 아직 실호출로 확인하지 않았다
(#54 댓글엔 getPubFullTextInfoSearch만). 처음에는 `--only <발송번호> --dry-run`으로 칸을 보고,
`--only <발송번호>` 한 건으로 응답을 확인한다.

실행: uv run python scripts/fetch_noise_c_candidates.py [--only <발송번호>] [--dry-run]
"""

import argparse
import os
import sys
import time
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

URL = "http://plus.kipris.or.kr/kipo-api/kipi/patUtiModInfoSearchSevice/getAdvancedSearch"
SLEEP_S = 1.0  # 호출 사이 쉼
MAX_CALLS = 40  # 한 번 실행에 부르는 최대 수 (30 OA + 여유). 월 1,000건 무료 한도 안


def params_for(q: dict, rows: int, join: str) -> dict:
    """한 OA의 검색 칸 (키는 넣지 않는다: 부를 때만 붙인다)."""
    return {
        "ipcNumber": q["ipc"],
        "claimScope": join.join(q["words"]),
        "patent": "true",
        "utility": "false",
        "numOfRows": str(rows),
        "pageNo": "1",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", default="data/goldsets/tune/retrieval/cite_c_queries.yaml")
    ap.add_argument("--out", default="work/kipris_c")
    ap.add_argument("--only", help="이 발송번호 하나만")
    ap.add_argument("--rows", type=int, default=30)
    # 낱말 잇기: KIPRIS 검색식에서 '+'는 OR, '*'는 AND (안내 화면 기준, 실호출로 확인 전)
    ap.add_argument("--join", default="+")
    ap.add_argument("--dry-run", action="store_true", help="부르지 않고 칸만 보인다")
    args = ap.parse_args(argv)

    qp = Path(args.queries)
    if not qp.is_file():
        print(f"질의 표가 없다: {qp.name}", file=sys.stderr)
        return 1
    queries = yaml.safe_load(qp.read_text(encoding="utf-8")) or {}
    if args.only:
        if args.only not in queries:
            print(f"질의 표에 없는 발송번호: {args.only}", file=sys.stderr)
            return 1
        queries = {args.only: queries[args.only]}
    if not queries:
        print("질의 표가 0줄이다", file=sys.stderr)
        return 1
    bad = [k for k, q in queries.items() if not q.get("ipc") or not q.get("words")]
    if bad:
        print(f"IPC나 낱말이 빈 OA (질의 표 채우기): {', '.join(bad)}", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    todo = [k for k in sorted(queries) if not (out / f"{k}.xml").exists()]
    skipped = len(queries) - len(todo)
    if len(todo) > MAX_CALLS:
        print(f"부를 OA {len(todo)}개가 상한 {MAX_CALLS}을 넘는다", file=sys.stderr)
        return 1
    if args.dry_run:
        for k in todo:
            print(f"{k}: {URL} {params_for(queries[k], args.rows, args.join)}")
        print(f"부를 것 {len(todo)}, 이미 받음 {skipped}", file=sys.stderr)
        return 0

    load_dotenv()
    key = os.getenv("KIPRIS_PLUS_API_KEY")
    if not key:
        print(".env에 KIPRIS_PLUS_API_KEY가 없다", file=sys.stderr)
        return 1

    failed: list[str] = []
    for i, k in enumerate(todo):
        if i:
            time.sleep(SLEEP_S)
        p = params_for(queries[k], args.rows, args.join) | {"ServiceKey": key}
        try:
            r = requests.get(URL, params=p, timeout=60)
        except requests.RequestException as e:
            # 예외 글에 주소(키 포함)가 들어갈 수 있어 종류 이름만 쓴다
            print(f"{k}: 호출 실패 ({type(e).__name__})", file=sys.stderr)
            failed.append(k)
            continue
        if r.status_code != 200 or "<response" not in r.text:
            print(f"{k}: 응답 이상 (HTTP {r.status_code})", file=sys.stderr)
            failed.append(k)
            continue
        (out / f"{k}.xml").write_text(r.text.replace(key, "***"), encoding="utf-8")
        print(f"{k}: 저장", file=sys.stderr)
    print(
        f"받음 {len(todo) - len(failed)}, 이미 받음 {skipped}, 실패 {len(failed)}",
        file=sys.stderr,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
