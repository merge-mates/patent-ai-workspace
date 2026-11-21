"""노이즈 풀 표 만들기 (이슈 #178 T2, eval/GUIDE.md '인용문헌 둘째 점수 풀 표').

풀 표(cite_pool.yaml)는 노이즈 범위의 재료다. 11/21 첫 표(tune 10건, OA 8통)는 손으로 만들었고,
tune 30건부터는 이 명령으로 만든다.
- docs: `data/raw/cited_v2/<출원번호>/<doc_id>.pdf` 공보마다 첫 쪽의
  (21) 출원번호(숫자만)와 (43) 공개일자 / (45) 등록공고일. 비특허 파일(doc_id 꼴이 아님)은
  날짜를 못 읽어 옛 표에 있는 `NPL-…` 줄을 그대로 가져온다
  (비특허는 노이즈로 안 써서 점수 영향 없음).
- oas: 인용 특허가 있는 사건마다 `data/processed/cases/<출원번호>/<발송번호>/`의 발송번호,
  우선일은 사건 목록 CSV(출원번호·우선일 칸) 또는 옛 표의 같은 출원 값.

실행: uv run python -m eval.retrieval.cite_pool --priority-csv <사건 목록 CSV>
      [--old retrieval/cite_pool.yaml]
      (기본 --out retrieval/cite_pool_t30.yaml. 이미 있으면 덮지 않는다)
메시지에는 doc_id·건수만 쓴다.
"""

import argparse
import re
import sys
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from eval.common.errors import EvalError
from eval.common.goldset import gold_path
from eval.retrieval.errors import RetrievalEvalError
from eval.retrieval.noise_scope import NPL_PREFIX, PoolTable

DOC_ID = re.compile(r"^(KR|US)\d+[A-Z]\d?$")  # cited-patents.md의 doc_id 꼴 (파일 이름)
_KR_DATE = r"(\d{4})년(\d{1,2})월(\d{1,2})일"
_US_DATE = r"([A-Z][a-z]{2})\.?(\d{1,2}),(\d{4})"


def _kr(m: re.Match) -> date:
    return date(int(m[1]), int(m[2]), int(m[3]))


def _us(m: re.Match) -> date:
    return datetime.strptime(f"{m[1]} {m[2]} {m[3]}", "%b %d %Y").date()


def parse_front(text: str) -> tuple[str, date]:
    """공보 첫 쪽 글 → (출원번호 숫자만, 처음 공개된 날). 못 읽으면 멈춘다.

    스캔본 미국 공보는 글자 사이에 빈칸이 끼어 나온다 ('( 21 ) Appl. No. : 15 /1 89'),
    그래서 빈칸을 모두 지운 글에서 찾는다.
    """
    t = re.sub(r"\s+", "", text)
    # 번호 꼴을 딱 맞춘다: 빈칸을 지워서 뒤 숫자(등록번호 등)가 붙어 나올 수 있다
    app = re.search(r"\(21\)출원번호(\d{2}-\d{4}-\d{7})", t) or re.search(
        r"\(21\)Appl\.No\.:?(\d{2}/\d{3},\d{3})", t
    )
    # 공개공보는 (43) 공개일, 등록공보는 (45) 등록공고일 (GUIDE 칸 정의)
    found = (
        (re.search(r"\(43\)공개일자" + _KR_DATE, t), _kr),
        (re.search(r"\(45\)공고일자" + _KR_DATE, t), _kr),
        (re.search(r"\(43\)Pub\.Date:" + _US_DATE, t), _us),
        (re.search(r"\(45\)DateofPatent:" + _US_DATE, t), _us),
    )
    d = next((conv(m) for m, conv in found if m), None)
    if not app or d is None:
        raise RetrievalEvalError("공보 첫 쪽에서 (21) 출원번호나 (43)/(45) 날짜를 못 읽었다")
    return re.sub(r"\D", "", app[1]), d


def read_first_page(path: Path) -> str:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        return pdf.pages[0].extract_text() or ""


def build_pool(
    cited_dir: Path,
    cases_dir: Path,
    priority: dict[str, date],
    old: PoolTable | None,
    read: Callable[[Path], str] = read_first_page,
) -> tuple[PoolTable, dict]:
    """풀 표와 건수 보고. priority = 출원번호 → 우선일 (옛 표 값으로 채운 뒤 넘긴다)."""
    docs: dict[str, dict] = {}
    oas: dict[str, dict] = {}
    skipped_npl = 0
    for app_dir in sorted(
        p for p in cited_dir.iterdir() if p.is_dir() and not p.name.startswith("_")
    ):
        pdfs = sorted(app_dir.glob("*.pdf"))
        patents = [p for p in pdfs if DOC_ID.match(p.stem)]
        skipped_npl += len(pdfs) - len(patents)
        if not patents:
            continue
        for p in patents:
            try:
                app_no, d = parse_front(read(p))
            except RetrievalEvalError as e:
                raise RetrievalEvalError(f"{p.stem}: {e}") from None
            docs[p.stem] = {"app_no": app_no, "date": d}
        case = cases_dir / app_dir.name
        oa_dirs = [p.name for p in case.iterdir() if p.is_dir()] if case.is_dir() else []
        if len(oa_dirs) != 1:
            # tune은 사건마다 OA 하나다. 0개·여러 개면 어느 OA인지 모른다
            raise RetrievalEvalError(f"사건 OA 폴더가 {len(oa_dirs)}개다 (1개여야 함)")
        if app_dir.name not in priority:
            raise RetrievalEvalError(f"우선일을 모르는 OA: {oa_dirs[0]}")
        oas[oa_dirs[0]] = {"app_no": app_dir.name, "priority_date": priority[app_dir.name]}
    if old is not None:
        for k, v in old.docs.items():
            if k.startswith(NPL_PREFIX):
                docs.setdefault(k, {"app_no": None, "date": v.date})
    if not docs:
        raise RetrievalEvalError("풀 표에 넣을 공보가 0개다")
    table = PoolTable.model_validate({"docs": docs, "oas": oas})
    return table, {"docs": len(docs), "oas": len(oas), "skipped_npl_files": skipped_npl}


def load_priority_csv(path: Path) -> dict[str, date]:
    import csv

    with path.open(encoding="utf-8-sig", newline="") as f:
        out = {}
        for r in csv.DictReader(f):
            s = (r.get("우선일") or r.get("출원일") or "").replace(".", "").replace("-", "").strip()
            if s:
                out[r["출원번호"]] = datetime.strptime(s, "%Y%m%d").date()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="eval.retrieval.cite_pool")
    ap.add_argument("--goldsets-root", default="data/goldsets")
    ap.add_argument("--goldset", default="tune")  # report 세트에는 만들지 않는다 (11/21)
    ap.add_argument("--old", default="retrieval/cite_pool.yaml")
    ap.add_argument("--out", default="retrieval/cite_pool_t30.yaml")
    ap.add_argument("--cited", default="data/raw/cited_v2")
    ap.add_argument("--cases", default="data/processed/cases")
    ap.add_argument("--priority-csv")
    args = ap.parse_args(argv)

    import yaml

    try:
        root = Path(args.goldsets_root)
        old_p, out_p = (gold_path(root, args.goldset, rel) for rel in (args.old, args.out))
        if out_p.exists():
            raise RetrievalEvalError(f"출력 표가 이미 있다 (덮지 않는다): {out_p.name}")
        old = None
        if old_p.is_file():
            old = PoolTable.model_validate(yaml.safe_load(old_p.read_text(encoding="utf-8")))
        priority = {v.app_no: v.priority_date for v in old.oas.values()} if old else {}
        if args.priority_csv:
            priority |= load_priority_csv(Path(args.priority_csv))
        table, rep = build_pool(Path(args.cited), Path(args.cases), priority, old)
        out_p.write_text(
            yaml.safe_dump(
                table.model_dump(mode="json", exclude={"docs": {"__all__": {"only_oas"}}}),
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
    except (EvalError, OSError, ValueError, yaml.YAMLError) as e:
        print(f"풀 표 만들기 실패: {e}", file=sys.stderr)
        return 1
    print(f"풀 표 저장: {rep}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
