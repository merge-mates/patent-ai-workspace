"""C안 노이즈 공보 PDF 받기 (이슈 #178 T3, KIPRIS Plus 공개·공고 전문).

한 번 쓰는 받기 스크립트다 (CLAUDE.md 코드 규칙 예외: 캐시·호출 상한 모듈을 거치지 않는다).
대신 이미 받은 PDF면 그 문헌은 부르지 않고, 호출 사이를 쉬고, 키를 출력·저장하지 않는다.

- 입력: C안 풀 표 <goldsets_root>/tune/retrieval/cite_pool_bc.yaml 에서 `only_oas`가 있는 문헌
  (eval.retrieval.noise_c가 만든 표)
- 호출: 문헌마다 전문 조회 1번 (공개공보 A → getPubFullTextInfoSearch,
  등록공보 B1 → getAnnFullTextInfoSearch, 출원번호로) + 응답의 PDF 주소에서 받기 1번.
  getPubFullTextInfoSearch는 #54 댓글에서 실호출 `00`을 확인했다. getAnnFullTextInfoSearch와
  응답 칸 이름(path)은 안내 화면 기준이라 처음에는 `--only <doc_id>` 한 건으로 확인한다.
- 저장: data/raw/cited_v2/noise_c/<doc_id>.pdf (색인 명령이 raw_root 아래를 다 읽는다),
  전문 조회 응답은 work/kipris_c_fulltext/<doc_id>.xml (키는 ***로 가림)
- 키: .env의 KIPRIS_PLUS_API_KEY (Open API 무료 옵션, 월 1,000건. 115건이면 전문 조회 115)

실행: uv run python scripts/fetch_noise_c_pdfs.py [--only <doc_id>] [--dry-run]
"""

import argparse
import os
import sys
import time
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # eval 패키지를 쓰려고
from eval.common.errors import EvalError  # noqa: E402
from eval.retrieval.noise_c import fulltext_kind, parse_fulltext_path  # noqa: E402

BASE = "http://plus.kipris.or.kr/kipo-api/kipi/patUtiModInfoSearchSevice/"
OPS = {"pub": "getPubFullTextInfoSearch", "ann": "getAnnFullTextInfoSearch"}
SLEEP_S = 1.0  # 호출 사이 쉼
MAX_DOCS = 150  # 한 번 실행에 부르는 최대 문헌 수 (115 + 여유). 월 1,000건 무료 한도 안


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", default="data/goldsets/tune/retrieval/cite_pool_bc.yaml")
    ap.add_argument("--out", default="data/raw/cited_v2/noise_c")
    ap.add_argument("--responses", default="work/kipris_c_fulltext")
    ap.add_argument("--only", help="이 doc_id 하나만")
    ap.add_argument("--dry-run", action="store_true", help="부르지 않고 할 일만 보인다")
    args = ap.parse_args(argv)

    pool_p = Path(args.pool)
    if not pool_p.is_file():
        print(f"C안 풀 표가 없다: {pool_p.name}", file=sys.stderr)
        return 1
    docs = yaml.safe_load(pool_p.read_text(encoding="utf-8")).get("docs") or {}
    todo_all = {k: v["app_no"] for k, v in docs.items() if v.get("only_oas")}
    if args.only:
        if args.only not in todo_all:
            print(f"C안 문헌이 아니다: {args.only}", file=sys.stderr)
            return 1
        todo_all = {args.only: todo_all[args.only]}
    if not todo_all:
        print("C안 문헌이 0개다 (noise_c로 풀 표를 먼저 만든다)", file=sys.stderr)
        return 1

    out, resp_dir = Path(args.out), Path(args.responses)
    todo = [k for k in sorted(todo_all) if not (out / f"{k}.pdf").exists()]
    skipped = len(todo_all) - len(todo)
    if len(todo) > MAX_DOCS:
        print(f"받을 문헌 {len(todo)}개가 상한 {MAX_DOCS}을 넘는다", file=sys.stderr)
        return 1
    try:
        kinds = {k: fulltext_kind(k) for k in todo}
    except EvalError as e:
        print(str(e), file=sys.stderr)
        return 1
    if args.dry_run:
        for k in todo:
            print(f"{k}: {OPS[kinds[k]]}")
        print(f"받을 것 {len(todo)}, 이미 받음 {skipped}", file=sys.stderr)
        return 0

    load_dotenv()
    key = os.getenv("KIPRIS_PLUS_API_KEY")
    if not key:
        print(".env에 KIPRIS_PLUS_API_KEY가 없다", file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    resp_dir.mkdir(parents=True, exist_ok=True)

    failed: list[str] = []
    for i, k in enumerate(todo):
        if i:
            time.sleep(SLEEP_S)
        params = {"applicationNumber": todo_all[k], "ServiceKey": key}
        try:
            r = requests.get(BASE + OPS[kinds[k]], params=params, timeout=60)
            body = r.text.replace(key, "***")
            (resp_dir / f"{k}.xml").write_text(body, encoding="utf-8")
            url = parse_fulltext_path(body)
            time.sleep(SLEEP_S)
            pdf = requests.get(url, timeout=120)
        except requests.RequestException as e:
            # 예외 글에 주소(키 포함)가 들어갈 수 있어 종류 이름만 쓴다
            print(f"{k}: 호출 실패 ({type(e).__name__})", file=sys.stderr)
            failed.append(k)
            continue
        except EvalError as e:
            print(f"{k}: {e}", file=sys.stderr)
            failed.append(k)
            continue
        if pdf.status_code != 200 or not pdf.content.startswith(b"%PDF"):
            print(f"{k}: PDF가 아니다 (HTTP {pdf.status_code})", file=sys.stderr)
            failed.append(k)
            continue
        (out / f"{k}.pdf").write_bytes(pdf.content)
        print(f"{k}: 저장 ({len(pdf.content) // 1024}KB)", file=sys.stderr)
    print(
        f"받음 {len(todo) - len(failed)}, 이미 받음 {skipped}, 실패 {len(failed)}",
        file=sys.stderr,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
