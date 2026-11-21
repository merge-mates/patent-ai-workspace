"""C안 노이즈 후보 고르기 (이슈 #178 T2).

C안: 인용문헌이 있는 OA마다 같은 IPC에서 청구항과 낱말이 비슷한 한국 공보 5건을
KIPRIS Plus로 고른다. 이 모듈은 네트워크를 부르지 않는다. 받기는
`scripts/fetch_noise_c_candidates.py`가 하고 OA마다 응답 XML을 git 밖 폴더
(기본 work/kipris_c/<발송번호>.xml)에 남긴다. 이 모듈은 그 파일을 읽어
- 넣는 조건(우선일 전 공개만, 그 출원 자신·풀 표에 이미 있는 특허와 같은 특허 빼기)으로 거르고
- 응답 순서(검색 순위) 앞에서 n건을 골라
- 풀 표(cite_pool.yaml)에 `only_oas: [그 OA]`를 단 문헌으로 더한 **새** 풀 표
  (cite_pool_bc.yaml)를 쓴다.
원래 풀 표는 덮지 않는다. 범위 파일은 그다음 noise_scope 명령에 --pool로 새 표를 주어 만든다.

비특허 문헌은 공보 검색에 나오지 않는다. 정답 인용문헌은 모두 B안 풀 표에 있으니,
풀 표의 어느 문헌과 같은 특허(같은 출원번호)여도 뺀다 (정답과 같은 특허 빼기보다 넓다).

질의 표(cite_c_queries.yaml, git 밖): {발송번호: {ipc: "G06T 7/11", words: [낱말…]}}.
words는 `suggest_words`로 OA 당시 청구항 1에서 뽑아 사람이 고친다.

실행: uv run python -m eval.retrieval.noise_c
메시지에는 발송번호·doc_id·건수만 쓴다 (청구항 글자 금지).
"""

import argparse
import logging
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from eval.common.errors import EvalError
from eval.common.goldset import gold_path
from eval.retrieval.errors import RetrievalEvalError
from eval.retrieval.noise_scope import PoolOa, PoolTable

log = logging.getLogger(__name__)

PER_OA = 5  # 이슈 #178: OA마다 5건


@dataclass(frozen=True)
class Hit:
    """검색 결과 공보 하나. date = 처음 공개된 날 (공개공보, 없으면 등록공고)."""

    doc_id: str
    app_no: str
    date: date


def _text(el: ET.Element, tag: str) -> str:
    found = el.find(tag)
    return (found.text or "").strip() if found is not None else ""


def _ymd(s: str) -> date:
    return datetime.strptime(s.replace("-", "").replace(".", ""), "%Y%m%d").date()


def parse_search_xml(body: str) -> list[Hit]:
    """KIPRIS Plus 공보 검색 응답 → Hit 목록 (응답 순서 그대로).

    doc_id 꼴은 cited-patents.md와 같다: 공개 10-2011-0000001 → KR20110000001A,
    공개 없이 등록만 있으면 등록번호 앞 9자리 + B1 (KR101234567B1).
    """
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise RetrievalEvalError("KIPRIS 응답을 XML로 읽을 수 없다") from None
    code = root.findtext(".//header/resultCode", default="").strip()
    if code and code != "00":
        # 키 오류·한도 초과 같은 실패를 0건으로 오해하지 않게 멈춘다
        raise RetrievalEvalError(f"KIPRIS 응답 코드가 정상이 아니다: {code}")
    hits: list[Hit] = []
    for it in root.iter("item"):
        app = _text(it, "applicationNumber")
        open_no, open_d = _text(it, "openNumber"), _text(it, "openDate")
        reg_no, reg_d = _text(it, "registerNumber"), _text(it, "registerDate")
        if open_no and open_d:
            hits.append(Hit(doc_id=f"KR{open_no[2:]}A", app_no=app, date=_ymd(open_d)))
        elif reg_no and reg_d:
            hits.append(Hit(doc_id=f"KR{reg_no[:9]}B1", app_no=app, date=_ymd(reg_d)))
        # 공개도 등록도 없으면 날짜를 몰라 우선일 조건을 못 본다: 넣지 않는다
    return hits


def pick_candidates(
    hits: list[Hit], oa: PoolOa, known_apps: set[str], known_doc_ids: set[str], n: int = PER_OA
) -> list[Hit]:
    """넣는 조건을 지난 것을 응답 순서대로 n건. 같은 특허는 한 번만 넣는다."""
    out: list[Hit] = []
    seen_apps = set(known_apps)
    for h in hits:
        if len(out) >= n:
            break
        if h.doc_id in known_doc_ids or h.app_no == oa.app_no or h.app_no in seen_apps:
            continue
        if h.date >= oa.priority_date:  # 당일 공개도 뺀다 (noise_scope와 같은 규칙)
            continue
        out.append(h)
        seen_apps.add(h.app_no)
    return out


# 청구항에 늘 나오는 말 (검색 낱말로 쓸모없음)
_STOP = {
    "상기",
    "포함",
    "포함하는",
    "및",
    "또는",
    "있어서",
    "특징으로",
    "것을",
    "것",
    "위한",
    "의해",
}
# 낱말 끝에서 떼는 조사 (긴 것부터)
_JOSA = ("에서", "으로", "을", "를", "은", "는", "이", "가", "의", "에", "로", "와", "과")


def suggest_words(claim: str, n: int = 5) -> list[str]:
    """청구항 글에서 자주 나온 낱말 n개 (같은 수면 먼저 나온 것). 사람이 고치는 초안이다."""
    counts: Counter[str] = Counter()
    first: dict[str, int] = {}
    for tok in re.findall(r"[가-힣A-Za-z0-9]+", claim.replace("<br />", " ")):
        if re.search(r"\d", tok) or tok.endswith("하는") or tok.endswith("되는"):
            continue  # 제1항에·검출하는 같은 말
        for j in _JOSA:
            if tok.endswith(j) and len(tok) - len(j) >= 2:
                tok = tok[: -len(j)]
                break
        if len(tok) < 2 or tok in _STOP or tok.endswith("는"):
            continue  # 조사를 못 뗀 '받는'·'찾는' 같은 꾸밈말
        counts[tok] += 1
        first.setdefault(tok, len(first))
    return sorted(counts, key=lambda w: (-counts[w], first[w]))[:n]


def claim1_text(history: str) -> str:
    """청구항 이력(`<출원>_청구항이력.txt`, ¶로 나눈 칸)에서 마지막 1항 글.

    입력 폴더(data/processed/cases/)는 OA에서 잘라 둔 것이라 마지막 1항 = OA 당시 1항이다.
    """
    lines = [ln.split("¶") for ln in history.splitlines() if ln.strip()]
    if not lines:
        raise RetrievalEvalError("청구항 이력이 비었다")
    head = lines[0]
    try:
        i_no, i_text = head.index("청구항번호"), head.index("청구항")
    except ValueError:
        raise RetrievalEvalError("청구항 이력 머리 칸이 맞지 않다") from None
    ones = [r[i_text] for r in lines[1:] if len(r) > i_text and r[i_no].strip() == "1"]
    if not ones:
        raise RetrievalEvalError("청구항 이력에 1항이 없다")
    return ones[-1].strip()


def _first_ipc(row: dict[str, str]) -> str:
    # 컴퓨터 비전 IPC(CV_IPC)가 있으면 그 첫째, 없으면 전체 IPC 첫째
    for col in ("CV_IPC", "IPC"):
        first = (row.get(col) or "").split(";")[0].strip()
        if first:
            return first
    return ""


def draft_queries(
    oas: dict[str, PoolOa], cases_dir: Path, ipc_csv: Path, n_words: int = 5
) -> dict[str, dict]:
    """질의 표 초안 {발송번호: {ipc, words}}. IPC가 목록에 없으면 빈칸으로 두어 사람이 채운다."""
    import csv

    with ipc_csv.open(encoding="utf-8-sig", newline="") as f:
        ipc_by_oa = {r["OA발송번호"]: _first_ipc(r) for r in csv.DictReader(f)}
    out: dict[str, dict] = {}
    for oa_no, oa in sorted(oas.items()):
        hist = cases_dir / oa.app_no / oa_no / f"{oa.app_no}_청구항이력.txt"
        if not hist.is_file():
            raise RetrievalEvalError(f"청구항 이력이 없다: {oa_no}")
        words = suggest_words(claim1_text(hist.read_text(encoding="utf-8")), n=n_words)
        ipc = ipc_by_oa.get(oa_no, "")
        if not ipc:
            log.warning("IPC를 못 찾은 OA (질의 표에서 채우기): %s", oa_no)
        out[oa_no] = {"ipc": ipc, "words": words}
    return out


class CQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ipc: str = Field(min_length=1)
    words: list[str] = Field(min_length=1)


def load_queries(path: Path) -> dict[str, CQuery]:
    import yaml

    if not path.is_file():
        raise RetrievalEvalError(f"질의 표가 없다: {path.name}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        out = {k: CQuery.model_validate(v) for k, v in raw.items()}
    except ValidationError, AttributeError, yaml.YAMLError:
        raise RetrievalEvalError(f"질의 표 꼴이 맞지 않다: {path.name}") from None
    if not out:
        raise RetrievalEvalError("질의 표가 0줄이다")
    return out


def add_c_docs(table: PoolTable, responses: Path, oa_nos: list[str]) -> tuple[PoolTable, dict]:
    """풀 표에 OA마다 C안 문헌을 더한 새 표와 건수 보고."""
    missing = [o for o in oa_nos if o not in table.oas]
    if missing:
        raise RetrievalEvalError(f"풀 표 oas에 발송번호가 없다: {', '.join(missing)}")
    docs = {k: v.model_dump() for k, v in table.docs.items()}
    known_apps = {v.app_no for v in table.docs.values() if v.app_no}
    per_oa: dict[str, int] = {}
    for oa_no in oa_nos:
        f = responses / f"{oa_no}.xml"
        if not f.is_file():
            raise RetrievalEvalError(f"응답 파일이 없다 (먼저 받기 스크립트): {oa_no}")
        hits = parse_search_xml(f.read_text(encoding="utf-8"))
        picked = pick_candidates(hits, table.oas[oa_no], known_apps, set(docs))
        if len(picked) < PER_OA:
            # 실패는 아니지만 줄마다 노이즈 수가 달라진다: 알린다
            log.warning("C안 후보가 %d건뿐인 OA: %s (응답 %d건)", len(picked), oa_no, len(hits))
        for h in picked:
            docs[h.doc_id] = {"app_no": h.app_no, "date": h.date, "only_oas": [oa_no]}
            known_apps.add(h.app_no)  # 다른 OA에 같은 특허가 또 나오면 한 번만
        per_oa[oa_no] = len(picked)
    new = PoolTable.model_validate({"docs": docs, "oas": table.model_dump()["oas"]})
    return new, {"oas": len(per_oa), "added": sum(per_oa.values()), "min": min(per_oa.values())}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="eval.retrieval.noise_c")
    ap.add_argument("--goldsets-root", default="data/goldsets")
    ap.add_argument("--goldset", default="tune")  # report 세트에는 만들지 않는다 (11/21)
    ap.add_argument("--pool", default="retrieval/cite_pool.yaml")
    ap.add_argument("--queries", default="retrieval/cite_c_queries.yaml")
    ap.add_argument("--out", default="retrieval/cite_pool_bc.yaml")
    ap.add_argument("--responses", default="work/kipris_c")
    # 질의 표 초안만 쓰고 끝낸다 (이미 있으면 덮지 않음). IPC 목록 CSV: OA발송번호·IPC·CV_IPC 칸
    ap.add_argument("--draft-queries", action="store_true")
    ap.add_argument("--cases", default="data/processed/cases")
    ap.add_argument("--ipc-csv")
    args = ap.parse_args(argv)

    import yaml

    try:
        root = Path(args.goldsets_root)
        pool_p, q_p, out_p = (
            gold_path(root, args.goldset, rel) for rel in (args.pool, args.queries, args.out)
        )
        if out_p == pool_p:
            raise RetrievalEvalError("--out이 원래 풀 표와 같다 (덮지 않는다)")
        if not pool_p.is_file():
            raise RetrievalEvalError(f"풀 표가 없다: {pool_p.name}")
        try:
            table = PoolTable.model_validate(yaml.safe_load(pool_p.read_text(encoding="utf-8")))
        except ValidationError as e:
            raise RetrievalEvalError(f"풀 표 꼴이 맞지 않다 ({e.error_count()}곳)") from None
        if args.draft_queries:
            if q_p.exists():
                raise RetrievalEvalError(f"질의 표가 이미 있다 (덮지 않는다): {q_p.name}")
            if not args.ipc_csv:
                raise RetrievalEvalError("--draft-queries에는 --ipc-csv가 필요하다")
            draft = draft_queries(table.oas, Path(args.cases), Path(args.ipc_csv))
            q_p.write_text(yaml.safe_dump(draft, allow_unicode=True), encoding="utf-8")
            print(f"질의 표 초안 저장: {len(draft)}개 OA (낱말·IPC를 사람이 확인)", file=sys.stderr)
            return 0
        queries = load_queries(q_p)
        new, rep = add_c_docs(table, Path(args.responses), sorted(queries))
        out_p.parent.mkdir(parents=True, exist_ok=True)
        body = new.model_dump(mode="json")
        for d in body["docs"].values():
            if d.get("only_oas") is None:
                d.pop("only_oas", None)  # B안 문헌은 원래 표 꼴 그대로 (비특허 app_no: null은 둔다)
        out_p.write_text(yaml.safe_dump(body, allow_unicode=True), encoding="utf-8")
    except (EvalError, OSError, yaml.YAMLError) as e:
        print(f"C안 풀 표 만들기 실패: {e}", file=sys.stderr)
        return 1
    print(f"C안 풀 표 저장: {rep}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
