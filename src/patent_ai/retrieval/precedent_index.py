"""판례·심결 청커: 판례 JSON(법제처)·심결 PDF(KIPRIS) → 법령 색인 law-idx-v3 조각 JSONL (#24 24c).

정한 것 (docs/features/F2/tasks.md m3-i1-24 24c, design 5-1·8절):
- 판례 74건 고르기: 받은 기록 셋에서 성공한 것 − v2 기록 `표시`가 붙은 것(신규성 아님 8건) −
  사건명 (상)·(디). 건수가 설정 값과 다르면 멈춘다 (숫자를 억지로 맞추지 않는다).
  `표시`가 붙어도 다른 주제(진보성·명확성) 기록에서 이미 성공한 사건은 그 주제의 판례라 남긴다.
- 판시사항·판결요지: `[1]` 칸마다 judgment_summary 조각 (speaker=court). 칸 표시 없으면 통째로 하나.
- 판례내용 【이 유】 아래: 줄(`<br/>`) 단위로 보고 `1.`(1단계)·`가.`(2단계) 번호 줄에서 새 조각.
  번호는 순서대로 올라갈 때만 번호로 본다 (문장 속 목록 `1.`이 조각을 가르지 않게).
  제목만 있는 1단계 줄은 아래 2단계 조각 글 앞에 붙인다. 판결 끝 서명(대법관·재판장·판사) 줄은 뺀다.
- speaker: 짧은 제목 줄로 정한다. 주장 → party, 판단·법리·결론·상고이유에 대하여·여부 → court,
  경위·기초사실·쟁점·원심 요지 → unknown, 주장과 판단이 함께 있는 제목 → unknown.
  제목이 없는 긴 줄은 위 단계 제목을 따르고, 그것도 없으면 대법원만 court, 나머지는 unknown.
- doc_id `판례_<사건번호>`, 판본 not_applicable, decided_on = 선고일자(못 읽으면 null + 경고).
- chunk_id `<index_version>:<doc_id>:<위치 키>`. 요지는 `s<n>`(판시사항)·`h<n>`(판결요지),
  이유는 `r<1단계 번호>-<2단계 번호>` (번호 없는 머리말은 `r0-0`).

심결 (task-c2):
- PDF는 `pdftotext -layout`. 쪽 번호 줄을 지우고 줄바꿈으로 끊긴 문장을 이은 뒤, "이 유" 제목
  아래를 판례와 같은 번호 규칙으로 자른다. [별지 N]부터와 심판관 서명 문단은 뺀다.
- doc_id `심결_<심판번호>`: 파일명 13자리 `<연도>101<번호 6자리>` → `2026원634` (101 = 원).
- decided_on = 머리의 "심 결 일" (못 찾으면 null + 경고),
  attrs 결과(주문의 취소/기각)·유형(폴더 이름).
- speaker는 판례와 같은 제목 규칙 (court = 판단하는 쪽, 심결은 심판부).
  제목이 없는 글의 기본값은 unknown (법원 이름이 없다).
- 위치 키는 판례 이유와 같다 (`r<1단계>-<2단계>`). 요지가 없어 chunk_kind는 judgment뿐이다.

실행: uv run python -m patent_ai.retrieval.precedent_index --config config/index/precedents.yaml
"""

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from patent_ai.index_version import is_index_version
from patent_ai.retrieval.errors import RetrievalError
from patent_ai.retrieval.law_index import write_jsonl
from patent_ai.retrieval.schemas import Chunk, Edition, Location, Speaker

logger = logging.getLogger(__name__)

_NOT_APPLICABLE = Edition(status="not_applicable")
_REASON_START = re.compile(r"【이\s*유】")
_SUMMARY_MARK = re.compile(r"\[(\d+)\]")
_LEVEL1 = re.compile(r"^(\d+)\.\s*(.*)$")
_LEVEL2 = re.compile(r"^([가나다라마바사아자차카타파하])\.\s*(.*)$")
# 번호로 시작하는 제목 줄 꼴: 1.  가.  (1)  1)  (가)  ①
_HEAD_MARK = re.compile(r"^(\d+\.|[가-하]\.|\(\d+\)|\d+\)|\([가-하]\)|[①-⑳])\s")
_HANGEUL_ORDER = "가나다라마바사아자차카타파하"
_SIGNATURE = re.compile(r"^(재판장\s*)?(대법관|판사|판\s사|재판장)(\s|$)")
# 제목으로 볼 줄 길이 (이보다 길면 문단 글이다)
_HEADING_MAX = 60
# 번호 앞 머리말이 이 글자 수보다 짧으면 조각으로 만들지 않는다
_PREAMBLE_MIN = 20
_EXCLUDED_CASE_NAME = re.compile(r"\((상|디)\)")

# 심결 PDF 글(pdftotext -layout)
_TRIAL_FILE = re.compile(r"^(\d{4})101(\d{6})$")  # 연도 4자리 + 종류 101(원) + 번호 6자리
_PAGE_NO = re.compile(r"^\s*(\d+\s*/\s*\d+|-\s*\d+\s*-)\s*$")  # 쪽 바닥의 "3/16", "- 1 -"
_TRIAL_DATE = re.compile(r"심\s*결\s*일\s+(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})")
_TRIAL_REASON_HEAD = re.compile(r"^이\s*유$")
# 머리 글에서 주문 칸: "주 문 <글> 청 구 취 지" (글이 제목과 한 문단으로 붙어 나오는 PDF도 있다)
_TRIAL_ORDER = re.compile(r"주\s*문\s+(.*?)\s*청\s*구\s*취\s*지", re.S)
_APPENDIX = re.compile(r"^\[별\s*지\s*\d+\s*\]")
_TRIAL_SIGN = re.compile(r"심판장|심판관")
_SIGN_MAX = 120  # 서명 블록은 짧다 (본문에 "심판관"이 나오는 긴 문단과 가른다)
_PARA_END = (".", ")", "」", "』", ":", ";", "?", "!")

_PARTY = re.compile(r"주장|항변")
_JUDGE = re.compile(
    r"판\s?단|소\s?결|결\s?론|법\s?리|이 법원|상고이유|에 대하여|에 관하여|살펴|여부|유무"
)
_UNKNOWN = re.compile(
    r"경위|기초\s?사실|쟁점|원심판결의 요지|원심의 판단|심결의 요지"
    r"|^이 사건 (출원|특허)?발명(의 요지)?$"
)


class PrecedentIndexError(RetrievalError):
    """판례·심결 색인을 만들 수 없다 (건수 불일치, 원본 모양이 틀림, 덮어쓰기 등)."""


def _clean_lines(text: str) -> list[str]:
    """`<br/>`를 줄바꿈으로, 줄 속 연속 공백을 하나로, 빈 줄은 버린다."""
    lines = (re.sub(r"\s+", " ", s).strip() for s in re.split(r"<br\s*/?>|\n", text))
    return [s for s in lines if s]


def _parse_date(raw: Any) -> date | None:
    try:
        return datetime.strptime(str(raw), "%Y%m%d").date()
    except ValueError:
        return None


def classify_heading(heading: str) -> Speaker | None:
    """짧은 제목 줄 하나 → 발언 주체. 제목으로 못 정하면 None."""
    h = re.sub(r"^(\d+|[가-하])\.\s*", "", heading).strip()
    if len(h) > _HEADING_MAX or not h:
        return None
    party, judge = bool(_PARTY.search(h)), bool(_JUDGE.search(h))
    if party and judge:
        return "unknown"  # "주장과 판단"처럼 둘이 섞인 제목
    if party:
        return "party"
    if _UNKNOWN.search(h):
        return "unknown"
    if judge:
        return "court"
    return None


def _speaker(court: str, h1: str | None, h2: str | None) -> Speaker:
    # 가까운 제목(2단계)부터 보고 못 정하면 위 단계, 그래도 없으면 법원 기준
    for h in (h2, h1):
        if h:
            s = classify_heading(h)
            if s:
                return s
    return "court" if court == "대법원" else "unknown"


def split_reasons(body: str) -> list[tuple[str, str, str | None, str | None, list[str]]]:
    """판례내용 → 【이 유】 아래 조각 목록 [(위치 키, label, 1단계 제목, 2단계 제목, 줄들)]."""
    m = _REASON_START.search(body)
    if not m:
        raise PrecedentIndexError("판례내용에 【이 유】가 없다")
    lines = _clean_lines(body[m.end() :])
    while lines and _SIGNATURE.match(lines[-1]):
        lines.pop()
    return split_numbered(lines)


def split_numbered(
    lines: list[str],
) -> list[tuple[str, str, str | None, str | None, list[str]]]:
    """문단(줄) 목록을 `1.`·`가.` 번호 줄에서 잘라 [(위치 키, label, 1단계 제목, 2단계 제목, 줄들)].

    1단계 제목만 있고 글이 없는 조각은 아래 2단계 조각에 제목을 붙이려고 따로 두지 않는다.
    판례(줄 = `<br/>` 단위)와 심결(줄 = 빈 줄로 나뉜 문단)이 같이 쓴다.
    """
    if not lines:
        raise PrecedentIndexError("【이 유】 아래 글이 없다")

    # 줄마다 (1단계 번호, 2단계 번호)를 정한다. 번호가 순서대로 이어질 때만 번호 줄로 본다.
    out: list[tuple[str, str, str | None, str | None, list[str]]] = []
    n1 = n2 = 0
    h1: str | None = None
    h2: str | None = None
    cur: list[str] = []
    cur_key = ("0", "0")
    cur_label = "이유"
    cur_h1: str | None = None
    cur_h2: str | None = None

    def flush() -> None:
        if cur:
            out.append((f"r{cur_key[0]}-{cur_key[1]}", cur_label, cur_h1, cur_h2, list(cur)))

    for line in lines:
        m1 = _LEVEL1.match(line)
        m2 = _LEVEL2.match(line)
        if m1 and (n1 == 0 or int(m1[1]) == n1 + 1):
            flush()
            n1, n2 = int(m1[1]), 0
            h1, h2 = line, None
            cur = [line]
            cur_key, cur_label = (str(n1), "0"), f"이유 {n1}."
            cur_h1, cur_h2 = h1, None
        elif m2 and n1 and _HANGEUL_ORDER.index(m2[1]) == n2:
            flush()
            n2 += 1
            h2 = line
            cur = [line]
            cur_key, cur_label = (str(n1), str(n2)), f"이유 {n1}. {m2[1]}."
            cur_h1, cur_h2 = h1, h2
        else:
            cur.append(line)
    flush()

    # 제목 한 줄뿐인 1단계 조각은 아래 2단계 조각이 제목을 이어받으므로 뺀다
    result = []
    for i, item in enumerate(out):
        key, _label, _h1, h2_, body_lines = item
        # 번호 앞 머리말이 "상고이유를 본다." 같은 한 마디뿐이면 검색할 내용이 없어 뺀다
        if key == "r0-0" and len("".join(body_lines)) < _PREAMBLE_MIN:
            continue
        has_child = i + 1 < len(out) and out[i + 1][0].split("-")[0] == key.split("-")[0]
        if key.endswith("-0") and len(body_lines) == 1 and h2_ is None and has_child:
            continue
        result.append(item)
    return result


def chunk_precedent(data: dict, index_version: str) -> list[Chunk]:
    """판례 JSON(PrecService 하나) → 요지·전문 조각 목록."""
    try:
        d = data["PrecService"]
        case_no = str(d["사건번호"]).strip()
    except KeyError, TypeError:
        raise PrecedentIndexError("판례 JSON에 PrecService.사건번호가 없다") from None
    if not case_no:
        raise PrecedentIndexError("판례 사건번호가 비었다")
    doc_id = f"판례_{case_no}"
    court = str(d.get("법원명") or "").strip()
    decided = _parse_date(d.get("선고일자"))
    if decided is None:
        logger.warning(
            "%s: 선고일자를 읽을 수 없어 decided_on=null (%r)", doc_id, d.get("선고일자")
        )
    attrs = {
        "법원명": court,
        "사건명": str(d.get("사건명") or "").strip(),
        "사건종류": str(d.get("사건종류명") or "").strip(),
    }

    def make(key: str, kind: str, label: str, seq: int, text: str, speaker: Speaker) -> Chunk:
        return Chunk(
            chunk_id=f"{index_version}:{doc_id}:{key}",
            index_version=index_version,
            doc_id=doc_id,
            chunk_kind=kind,  # type: ignore[arg-type]
            location=Location(kind="paragraph", start=seq, end=seq, label=label),
            edition=_NOT_APPLICABLE,
            text=text,
            source_kind="precedent",
            decided_on=decided,
            speaker=speaker,
            attrs=dict(attrs),
        )

    chunks: list[Chunk] = []
    # 판시사항(s)·판결요지(h): [n] 칸마다. 칸 표시 없으면 통째로 하나.
    for field, prefix in (("판시사항", "s"), ("판결요지", "h")):
        raw = d.get(field)
        if not raw or not str(raw).strip():
            continue
        text = "\n".join(_clean_lines(str(raw)))
        marks = list(_SUMMARY_MARK.finditer(text))
        if not marks:
            parts = [(1, text)]
        else:
            parts = [
                (
                    int(mk[1]),
                    text[mk.end() : (marks[i + 1].start() if i + 1 < len(marks) else None)],
                )
                for i, mk in enumerate(marks)
            ]
        for n, part in parts:
            part = part.strip()
            if part:
                label = f"{field} [{n}]" if marks else field
                chunks.append(make(f"{prefix}{n}", "judgment_summary", label, n, part, "court"))

    body = str(d.get("판례내용") or "")
    for i, (key, label, h1, h2, lines) in enumerate(split_reasons(body), start=1):
        # 2단계 조각에는 위 1단계 제목을 앞에 붙여 무슨 이야기인지 남긴다
        text_lines = [h1, *lines] if h2 and h1 else lines
        chunks.append(
            make(key, "judgment", label, i, "\n".join(text_lines), _speaker(court, h1, h2))
        )
    return chunks


# ---------- 심결 (task-c2) ----------


def trial_doc_id(file_name: str) -> str:
    """파일 이름 13자리 → doc_id. 2026101000634.pdf → 심결_2026원634 (101 = 거절결정불복 `원`)."""
    m = _TRIAL_FILE.match(Path(file_name).stem)
    if not m:
        raise PrecedentIndexError(
            f"심결 파일 이름이 심판번호 13자리(<연도>101<번호 6자리>)가 아니다: {file_name}"
        )
    return f"심결_{m[1]}원{int(m[2])}"


def read_trial_pages(path: str | Path) -> list[str]:
    """심결 PDF → 쪽별 글 (`pdftotext -layout`, poppler)."""
    try:
        r = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, check=True
        )
    except FileNotFoundError:
        raise PrecedentIndexError("pdftotext가 없다 (poppler 설치 필요)") from None
    except subprocess.CalledProcessError as e:
        raise PrecedentIndexError(f"PDF 글자를 못 읽었다: {path} ({e.stderr.strip()})") from None
    pages = r.stdout.split("\f")
    while pages and not pages[-1].strip():
        pages.pop()  # 끝 쪽 표시 뒤의 빈 조각
    return pages


def _is_heading(text: str) -> bool:
    """번호로 시작하고 짧으면 제목 줄 (문장이 이어 붙지 않는다)."""
    return len(text) <= _HEADING_MAX and _HEAD_MARK.match(text) is not None


def _trial_paragraphs(pages: list[str]) -> list[str]:
    """쪽 글 → 문단 목록. 쪽 번호 줄을 지우고, 줄바꿈으로 끊긴 문장을 공백으로 이어 붙인다.

    PDF마다 줄 사이에 빈 줄이 있기도 없기도 해서 빈 줄은 보지 않는다. 줄을 차례로 보며 앞 줄 끝이
    마침표 등이 아니면 같은 문장으로 보고 이어 붙인다 (쪽이 바뀌는 곳도 같다). 번호 제목 줄
    (`가. …`, `(1) …`)은 앞 줄에 잇지 않고, 제목 줄 아래 첫 줄도 제목에 잇지 않는다.
    """
    paras: list[str] = []
    for page in pages:
        for line in page.splitlines():
            if _PAGE_NO.match(line):
                continue
            b = re.sub(r"\s+", " ", line).strip()
            if not b:
                continue
            prev = paras[-1] if paras else ""
            is_open = len(prev) > 12 and not prev.endswith(_PARA_END) and not _is_heading(prev)
            if is_open and not _HEAD_MARK.match(b):
                paras[-1] = f"{prev} {b}"
            else:
                paras.append(b)
    return paras


def chunk_trial(
    pages: list[str], file_name: str, index_version: str, trial_type: str | None = None
) -> list[Chunk]:
    """심결 쪽 글 → 【이 유】 번호 문단마다 judgment 조각. 심결문엔 요지가 없어 전문만 있다."""
    doc_id = trial_doc_id(file_name)
    paras = _trial_paragraphs(pages)
    try:
        start = next(i for i, p in enumerate(paras) if _TRIAL_REASON_HEAD.match(p))
    except StopIteration:
        raise PrecedentIndexError(f"{doc_id}: '이 유' 제목 줄이 없다") from None

    # 심결일: 머리 표의 "심 결 일 2026. 10. 1."
    m = _TRIAL_DATE.search("\n".join(pages[:2]))
    decided = date(int(m[1]), int(m[2]), int(m[3])) if m else None
    if decided is None:
        logger.warning("%s: 심결일을 찾지 못해 decided_on=null", doc_id)

    # 결과: 주문 글에서 (취소/기각). 못 읽으면 null
    om = _TRIAL_ORDER.search(" ".join(paras[:start]))
    order = om[1] if om else ""
    result = "원결정 취소" if "취소" in order else "기각" if "기각" in order else None
    if result is None:
        logger.warning("%s: 주문에서 결과(취소·기각)를 읽지 못했다", doc_id)

    # 이유 글: [별지] 앞까지, 심판관 서명 문단은 뺀다
    body: list[str] = []
    for p in paras[start + 1 :]:
        if _APPENDIX.match(p):
            break
        if len(p) < _SIGN_MAX and _TRIAL_SIGN.search(p):
            continue
        body.append(p)

    attrs = {"결과": result, "유형": trial_type}
    chunks = []
    for i, (key, label, h1, h2, lines) in enumerate(split_numbered(body), start=1):
        text_lines = [h1, *lines] if h2 and h1 else lines
        chunks.append(
            Chunk(
                chunk_id=f"{index_version}:{doc_id}:{key}",
                index_version=index_version,
                doc_id=doc_id,
                chunk_kind="judgment",
                location=Location(kind="paragraph", start=i, end=i, label=label),
                edition=_NOT_APPLICABLE,
                text="\n".join(text_lines),
                source_kind="trial",
                decided_on=decided,
                # 판단 주체는 심판부 (judgment의 court와 같은 뜻으로 쓴다)
                speaker=_speaker("", h1, h2),
                attrs=dict(attrs),
            )
        )
    return chunks


def select_precedents(logs: list[list[dict]], expected: int) -> list[str]:
    """받은 기록들 → 색인할 판례 파일 이름(body_*.json) 목록. 건수가 expected가 아니면 멈춘다.

    1. 기록에서 status가 ok인 것.
    2. `표시`가 붙은 사건은 뺀다. 단 그 사건이 다른 주제 기록에서도 ok였으면 그 주제 판례라 남긴다.
    3. 사건명에 (상)·(디)가 있으면 뺀다.
    """
    ok_topics: dict[str, set[str]] = {}
    names: dict[str, str] = {}
    marked: dict[str, str] = {}  # 파일 이름 → 표시가 붙은 주제
    for log in logs:
        for rec in log:
            path = rec.get("path")
            if not path:
                continue
            fname = Path(path).name
            names[fname] = str(rec.get("사건명") or "")
            if rec.get("status") == "ok":
                ok_topics.setdefault(fname, set()).add(str(rec.get("topic")))
            if rec.get("표시"):
                marked[fname] = str(rec.get("topic"))
    picked = []
    for fname in sorted(ok_topics):
        if fname in marked and not (ok_topics[fname] - {marked[fname]}):
            continue
        if _EXCLUDED_CASE_NAME.search(names.get(fname, "")):
            continue
        picked.append(fname)
    if len(picked) != expected:
        raise PrecedentIndexError(
            f"고른 판례가 {len(picked)}건이다 (설정 값 {expected}건). 고르기 규칙·받은 기록 확인"
        )
    return picked


def build_precedent_chunks(cfg: dict) -> list[Chunk]:
    index_version = cfg["index_version"]
    if not is_index_version("law", index_version):
        raise PrecedentIndexError(f"법령 색인 판 이름이 아니다: {index_version}")
    raw_dir = Path(cfg["precedent_dir"])
    logs = []
    for name in cfg["precedent_logs"]:
        p = raw_dir / name
        if not p.exists():
            raise PrecedentIndexError(f"받은 기록이 없다: {p}")
        logs.append(json.loads(p.read_text(encoding="utf-8")))
    chunks: list[Chunk] = []
    for fname in select_precedents(logs, int(cfg["expected_precedents"])):
        p = raw_dir / fname
        if not p.exists():
            raise PrecedentIndexError(f"판례 파일이 없다: {p}")
        chunks.extend(chunk_precedent(json.loads(p.read_text(encoding="utf-8")), index_version))
    if not chunks:
        logger.warning("판례 조각이 0개다: %s", raw_dir)
        raise PrecedentIndexError("판례 조각이 0개다")
    return chunks


def build_trial_chunks(cfg: dict) -> list[Chunk]:
    index_version = cfg["index_version"]
    trial_dir = Path(cfg["trial_dir"])
    pdfs = sorted(trial_dir.glob("*/*.pdf"))
    expected = int(cfg["expected_trials"])
    if len(pdfs) != expected:
        raise PrecedentIndexError(
            f"심결 PDF가 {len(pdfs)}건이다 (설정 값 {expected}건): {trial_dir}"
        )
    chunks: list[Chunk] = []
    seen: set[str] = set()
    for pdf in pdfs:
        doc_id = trial_doc_id(pdf.name)
        if doc_id in seen:
            raise PrecedentIndexError(f"같은 심판번호 파일이 둘 이상이다: {doc_id}")
        seen.add(doc_id)
        # 유형은 폴더 이름 (신규성_진보성 → 신규성+진보성)
        chunks.extend(
            chunk_trial(
                read_trial_pages(pdf), pdf.name, index_version, pdf.parent.name.replace("_", "+")
            )
        )
    return chunks


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="판례·심결 원본 → law-idx-v3 조각 JSONL")
    ap.add_argument("--config", required=True, help="config/index/precedents.yaml")
    ap.add_argument("--force", action="store_true", help="있는 출력 파일을 덮어쓴다")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    try:
        out = Path(cfg["out"])
        if out.exists() and not args.force:
            raise PrecedentIndexError(f"이미 있는 파일이다 (--force로 덮어쓴다): {out}")
        chunks = build_precedent_chunks(cfg) + build_trial_chunks(
            cfg
        )  # 다 만든 뒤에 지워서, 실패해도 옛 파일이 남는다
        if out.exists():
            out.unlink()
        write_jsonl(chunks, out)
    except RetrievalError as e:
        logger.error("%s", e)
        return 1
    summary = sum(c.chunk_kind == "judgment_summary" for c in chunks)
    trials = [c for c in chunks if c.source_kind == "trial"]
    logger.info(
        "만듦: %s (조각 %d개: 요지 %d, 전문 %d / 판례 문서 %d개, 심결 문서 %d개 조각 %d개)",
        out,
        len(chunks),
        summary,
        len(chunks) - summary,
        len({c.doc_id for c in chunks if c.source_kind == "precedent"}),
        len({c.doc_id for c in trials}),
        len(trials),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
