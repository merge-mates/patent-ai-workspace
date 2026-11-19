"""은진 님 정답 JSON -> 계약 정답 파일 cite_gold.jsonl (design 3-1).

실행: uv run python -m eval.retrieval.convert_cite_gold --src <json> --cases data/raw/cases

읽는 사건 파일은 청구항이력·행정이력 둘뿐이다 (등록공보·결정본문은 안 읽음).
검증(GoldRow, find_leaks)을 메모리에서 다 끝낸 뒤에만 파일을 쓴다.
메시지에는 row_id·건수만 쓴다 (질의 글자 금지).
"""

import argparse
import hashlib
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from eval.retrieval.checks import find_leaks
from eval.retrieval.claim_history import OaNotFound, claims_at_oa_with_stats, expand_claims
from eval.retrieval.errors import RetrievalEvalError
from eval.retrieval.gold import GoldItem, GoldRow

log = logging.getLogger(__name__)

DEFAULT_CONFIG = Path(__file__).with_name("cite_gold.yaml")
# 한국 공보 표기는 그대로 doc_id (표에는 논문만 둔다)
_KR_LABEL = re.compile(r"^KR\d+[AB]\d?$")
_PARA = re.compile(r"^(\d+)(?:-(\d+))?$")
_FIG = re.compile(r"^(\d+)[A-Za-z]?(?:-(\d+)[A-Za-z]?)?$")  # "4c" -> 4, "3-4" -> 3, 4
_PAGE = re.compile(r"^\s*(\d+)\s*쪽")


@dataclass
class ConvertReport:
    rows: int = 0
    expanded: int = 0  # 범위 키("3-4")에서 나온 줄 수
    excluded: dict[str, int] = field(default_factory=lambda: {"same_as_other": 0, "no_location": 0})
    no_query_cases: int = 0  # 청구항이력·행정이력이 없거나 OA를 못 찾은 사건
    no_query_rows: int = 0  # 그 사건 때문에 못 쓴 줄
    claim_missing_rows: int = 0  # OA 당시 없거나 삭제된 청구항
    no_citation_reasons: int = 0  # 인용 없는 거절이유 (42조 등)
    unapplied_changes: int = 0  # 행정이력에 없는 접수의 청구항 변경

    def as_dict(self) -> dict:
        return {
            "rows": self.rows,
            "expanded": self.expanded,
            "excluded": dict(self.excluded),
            "no_query_cases": self.no_query_cases,
            "no_query_rows": self.no_query_rows,
            "claim_missing_rows": self.claim_missing_rows,
            "no_citation_reasons": self.no_citation_reasons,
            "unapplied_changes": self.unapplied_changes,
        }


def _resolve_doc(label: str, doc_ids: dict) -> tuple[str, int | None]:
    """정답 표기 -> (doc_id, 쪽 수 또는 None). 표에도 없고 KR 꼴도 아니면 멈춘다."""
    label = label.strip()
    entry = doc_ids.get(label)
    pages = None
    if isinstance(entry, dict):
        doc_id, pages = entry.get("doc_id"), entry.get("pages")
    elif isinstance(entry, str):
        doc_id = entry
    elif _KR_LABEL.match(label):
        doc_id = label
    else:
        raise RetrievalEvalError("doc_id 표에 없는 문헌 표기가 있다 (표에 한 줄 추가)")
    if not isinstance(doc_id, str) or not doc_id or re.search(r"[:\s]", doc_id):
        raise RetrievalEvalError("doc_id에 ':'나 공백이 있거나 비었다")
    return doc_id, pages


def _items(entry: dict, doc_id: str, pages: int | None) -> list[GoldItem]:
    """청구항별 칸 하나 -> 위치 항목들. 인식 못 하는 기타 글자는 버린다."""
    items: list[GoldItem] = []
    for s in entry.get("식별번호", []):
        m = _PARA.match(str(s).strip())
        if not m:
            raise RetrievalEvalError("식별번호 표기를 읽을 수 없다")
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        label = f"[{lo:04d}]" if hi == lo else f"[{lo:04d}]-[{hi:04d}]"
        items.append(GoldItem(kind="paragraph", start=lo, end=hi, label=label))
    for s in entry.get("도면", []):
        m = _FIG.match(str(s).strip())
        if not m:
            raise RetrievalEvalError("도면 표기를 읽을 수 없다")
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        figs = list(range(lo, hi + 1))
        items.append(
            GoldItem(kind="figure", figures=figs, label=f"도 {lo}" if hi == lo else f"도 {lo}-{hi}")
        )
    for s in entry.get("인용문헌_청구항", []):
        claims = expand_claims(str(s))
        items.append(GoldItem(kind="claim", claims=claims, label=f"청구항 {s}"))
    for s in entry.get("기타", []):
        s = str(s).strip()
        if s == "요약":
            items.append(GoldItem(kind="abstract", label="요약"))
            continue
        m = _PAGE.match(s)
        if m and doc_id.startswith("NPL"):
            n = int(m.group(1))
            if pages is not None and n > pages:
                raise RetrievalEvalError(f"쪽 번호가 문헌 쪽 수를 넘는다 ({doc_id})")
            items.append(GoldItem(kind="page", start=n, end=n, label=f"{n}쪽"))
        # 그 밖 기타 글자는 버린다
    return items


def _case_paths(cases_root: Path, app_no: str) -> tuple[Path, Path]:
    d = Path(cases_root) / app_no
    return d / f"{app_no}_청구항이력.txt", d / f"{app_no}_행정이력.txt"


def convert(
    gold_json: dict, cases_root: Path, doc_ids: dict
) -> tuple[list[GoldRow], ConvertReport]:
    rep = ConvertReport()
    rows: list[GoldRow] = []
    seen: set[str] = set()

    for case in gold_json.get("사건", []):
        app_no, oa_no = case.get("출원번호"), case.get("발송번호")
        if not app_no or not oa_no:
            raise RetrievalEvalError("사건에 출원번호·발송번호 칸이 없다")

        # 1단계: 이 사건에서 만들 줄의 뼈대 (질의는 아직 없음)
        # (순번, 청구항, doc_id, 항목들 또는 None=같은이유, 범위 키에서 왔나)
        specs: list[tuple[int, int, str, list[GoldItem] | None, bool]] = []
        for reason in case.get("거절이유", []):
            seq = reason["순번"]
            cites = reason.get("인용") or []
            if not cites:
                rep.no_citation_reasons += 1  # 42조처럼 인용이 없으면 줄을 안 만든다
                continue
            for cite in cites:
                doc_id, pages = _resolve_doc(cite["문헌"], doc_ids)
                have: set[int] = set()
                for key, entry in (cite.get("청구항별") or {}).items():
                    try:
                        claims = expand_claims(key)
                    except ValueError:
                        raise RetrievalEvalError(f"청구항 키를 읽을 수 없다 (r{seq})") from None
                    items = _items(entry, doc_id, pages)
                    for c in claims:
                        have.add(c)
                        specs.append((seq, c, doc_id, items, len(claims) > 1))
                # 같은이유: 정답 파일에서는 거절이유 칸에 있다 (그 거절이유의 모든 인용문헌에 적용).
                # 이미 청구항별에 있는 청구항은 건너뛰고 나머지만 same_as_other
                same_keys = {**(reason.get("같은이유") or {}), **(cite.get("같은이유") or {})}
                for key in same_keys:
                    try:
                        same = expand_claims(key)
                    except ValueError:
                        raise RetrievalEvalError(f"같은이유 키를 읽을 수 없다 (r{seq})") from None
                    for c in same:
                        if c not in have:
                            have.add(c)
                            specs.append((seq, c, doc_id, None, False))

        # 2단계: OA 당시 청구항 (질의). 파일·OA가 없으면 이 사건 줄은 모두 뺀다
        hist, admin = _case_paths(cases_root, app_no)
        try:
            claims_by_no, unapplied = claims_at_oa_with_stats(hist, admin, oa_no)
        except OSError, OaNotFound:
            rep.no_query_cases += 1
            rep.no_query_rows += len(specs)
            log.warning("질의를 못 만든 사건: 발송번호 %s (줄 %d개 뺌)", oa_no, len(specs))
            continue
        rep.unapplied_changes += unapplied

        # 3단계: 줄 만들기
        for seq, c, doc_id, items, from_range in specs:
            if c not in claims_by_no:
                rep.claim_missing_rows += 1  # OA 당시 없거나 삭제됨
                continue
            row_id = f"{oa_no}:r{seq}:c{c}:{doc_id}"
            if row_id in seen:
                raise RetrievalEvalError(f"row_id가 중복이다: {row_id}")
            seen.add(row_id)
            exclude = None
            if items is None:
                exclude, items = "same_as_other", []
            elif not items:
                exclude = "no_location"
                log.warning("위치 없음으로 뺌: %s", row_id)
            if exclude:
                rep.excluded[exclude] += 1
            if from_range:
                rep.expanded += 1
            try:
                rows.append(
                    GoldRow(
                        row_id=row_id,
                        corpus="cite",
                        query=claims_by_no[c],
                        doc_ids=[doc_id],
                        items=items,
                        exclude=exclude,
                    )
                )
            except ValidationError:
                # 원인 메시지에 질의가 섞일 수 있어 row_id만
                raise RetrievalEvalError(f"정답 줄 꼴이 맞지 않는다: {row_id}") from None
    rep.rows = len(rows)
    return rows, rep


def _next_version(goldsets_root: Path, out: Path, new_bytes: bytes) -> int | None:
    """VERSION을 새로 쓸 값. 바꿀 필요가 없으면 None.

    VERSION이 없으면 1. 있으면 새 파일 sha256이 기존 파일과 다를 때만 +1 (기존 파일이 없으면 다름).
    """
    vf = goldsets_root / "VERSION"
    if not vf.is_file():
        return 1
    try:
        cur = int(vf.read_text().strip())
    except ValueError:
        raise RetrievalEvalError("정답 세트 VERSION 파일이 정수가 아니다") from None
    if (
        out.is_file()
        and hashlib.sha256(out.read_bytes()).digest() == hashlib.sha256(new_bytes).digest()
    ):
        return None
    return cur + 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="eval.retrieval.convert_cite_gold")
    ap.add_argument("--src", required=True, help="은진 님 정답 JSON")
    ap.add_argument("--cases", default=None, help="사건 폴더 뿌리 (기본: 설정의 cases_root)")
    ap.add_argument("--goldsets-root", default="data/goldsets")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--report", default=None, help="변환 보고 경로 (기본: 설정의 report)")
    args = ap.parse_args(argv)

    try:
        cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {}
        root = Path(args.goldsets_root)
        cases = Path(args.cases or cfg["cases_root"])
        report_path = Path(args.report or cfg["report"])
        out = root / cfg["output"]
        table_path = root / cfg["doc_ids_table"]
        if not table_path.is_file():
            raise RetrievalEvalError(f"doc_id 표가 없다: {table_path.name}")
        doc_ids = yaml.safe_load(table_path.read_text(encoding="utf-8")) or {}
        try:
            gold_json = json.loads(Path(args.src).read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            raise RetrievalEvalError("정답 JSON을 읽을 수 없다") from None

        rows, rep = convert(gold_json, cases, doc_ids)
        if not rows:
            raise RetrievalEvalError("변환 결과가 0줄이다")
        # 질의 누출 검사: 걸린 줄의 row_id와 건수만 알린다
        leaked = {r.row_id: n for r in rows if (n := len(find_leaks(r)))}
        if leaked:
            ids = ", ".join(f"{k}({n}항목)" for k, n in leaked.items())
            raise RetrievalEvalError(f"질의에 정답 위치 표기가 있는 줄 {len(leaked)}건: {ids}")

        # 여기까지 메모리에서 끝났을 때만 쓴다
        body = "".join(
            json.dumps(r.model_dump(mode="json"), ensure_ascii=False) + "\n" for r in rows
        )
        data = body.encode("utf-8")
        version = _next_version(root, out, data)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        if version is not None:
            (root / "VERSION").write_text(f"{version}\n")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(rep.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except RetrievalEvalError as e:
        print(f"변환 실패: {e}", file=sys.stderr)
        return 1
    except (OSError, KeyError, yaml.YAMLError) as e:
        print(f"변환 실패: {type(e).__name__}", file=sys.stderr)
        return 1

    # 끝에 이유별 빼는 건수를 경고 한 줄로
    log.warning(
        "변환 끝: 줄 %d, no_location %d, same_as_other %d, 질의 없음 사건 %d(줄 %d), "
        "청구항 없음 %d, 청구항이력 접수 불일치 %d",
        rep.rows,
        rep.excluded["no_location"],
        rep.excluded["same_as_other"],
        rep.no_query_cases,
        rep.no_query_rows,
        rep.claim_missing_rows,
        rep.unapplied_changes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
