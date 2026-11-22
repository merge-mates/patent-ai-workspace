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
from dataclasses import dataclass
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
_HEAD_MARK = re.compile(r"^(\d+\.|[가-하]\.|\(\d+\)|\d+\)|[가-하]\)|\([가-하]\)|[⑴-⒇]|[①-⑳])\s")
# 3단계 번호 제목 꼴: 1)  (1)  ⑴  가)  (가)
_LEVEL3 = re.compile(r"^(\d+\)|\(\d+\)|[⑴-⒇]|[가-하]\)|\([가-하]\))\s*(.*)$")
_ANY_MARK = re.compile(r"^(\d+\.|[가-하]\.|\d+\)|\(\d+\)|[⑴-⒇]|[가-하]\)|\([가-하]\))\s*")
_HANGEUL_ORDER = "가나다라마바사아자차카타파하"
_SIGNATURE = re.compile(r"^(재판장\s*)?(대법원장|대법관|판사|판\s사|재판장)(\s|$)")
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
# 줄 맨 앞의 [별지 1]·별지 1]·별지 1:·[별지] 제목. "[별지]의 1 기재와 같다" 같은 문장 속 줄은 아니다
_APPENDIX = re.compile(r"^\[?\s*별\s*지\s*\d*\s*(\](\s|$)|:)")
_SEAL_NUMBERS = re.compile(r"^[\d\s]{5,}$")  # 서명 옆 직인 번호 줄 "19990065 20050153"
_TRIAL_SIGN = re.compile(r"심판장|심판관")
_SIGN_MAX = 120  # 서명 블록은 짧다 (본문에 "심판관"이 나오는 긴 문단과 가른다)
_PARA_END = (".", ")", "」", "』", ":", ";", "?", "!")

_PARTY = re.compile(r"주장|항변")
_JUDGE = re.compile(
    r"판\s?단|소\s?결|결\s?론|법\s?리|이 법원|상고이유|에 대하여|에 관하여|살펴|여부|유무"
)
_STRONG_JUDGE = re.compile(r"판\s?단|소\s?결|결\s?론|이 법원")
# 짧은 제목 꼴 줄이 번호를 건너뛰어도 받는 최대 폭 (날짜 "2025. 3. 7."이 제목이 되지 않게)
_SKIP_MAX = 2
# 주장 아래에서 court로 바꾸는 제목의 최대 길이 (주장 문장 속 "판단"은 제외)
_COURT_HEADING_MAX = 20
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
    h = _ANY_MARK.sub("", heading, count=1).strip()
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


def _is_court_heading(heading: str) -> bool:
    """ "판단"·"소결"·"결론"만 있는 짧은 제목 (문장이 아니라 제목)."""
    h = _ANY_MARK.sub("", heading, count=1).strip()
    return len(h) <= _COURT_HEADING_MAX and _STRONG_JUDGE.search(h) is not None


def _speaker(heads: list[str]) -> Speaker:
    """가장 가까운(깊은) 제목부터 위로 보고, 제목으로 못 정하면 unknown (design 8절).

    당사자 주장 제목 아래의 소제목은 주장 안의 글이라 party로 둔다. "…여부", 주장 문장 속 "판단"도
    마찬가지이고, "심판부의 판단"처럼 20자 이하 제목에 판단·소결·결론이 있어야 court로 바뀐다.
    """
    for i in range(len(heads) - 1, -1, -1):
        s = classify_heading(heads[i])
        if s == "court" and not _is_court_heading(heads[i]):
            if any(classify_heading(h) == "party" for h in heads[:i]):
                return "party"
        if s:
            return s
    return "unknown"


@dataclass
class _Part:
    """번호로 자른 조각 하나. heads는 위 단계부터 자기 제목까지, lines는 자기 제목 줄부터의 글."""

    key: str
    label: str
    heads: list[str]
    lines: list[str]


def split_reasons(body: str) -> list[_Part]:
    """판례내용 → 【이 유】 아래 조각 목록."""
    m = _REASON_START.search(body)
    if not m:
        raise PrecedentIndexError("판례내용에 【이 유】가 없다")
    lines = _clean_lines(body[m.end() :])
    while lines and _SIGNATURE.match(lines[-1]):
        lines.pop()
    return split_numbered(lines)


def _level2_ok(letter: str, n2: int, short: bool) -> bool:
    idx = _HANGEUL_ORDER.index(letter)
    return idx == n2 or (short and n2 - 1 <= idx <= n2 + _SKIP_MAX - 1)


def split_numbered(lines: list[str]) -> list[_Part]:
    """문단(줄) 목록을 번호 제목 줄에서 잘라 조각 목록으로.

    - 1단계 `1.`, 2단계 `가.`: 번호가 순서대로 이어질 때만 번호 줄로 본다. 단 60자 이하 제목 꼴
      줄은 같은 번호·건너뛴 번호도 다시 맞춘다 (잘못 받은 번호가 뒤 진짜 제목을 삼키지 않게).
    - 3단계 `1)` `(1)` `⑴` `가)`: 60자 이하이고 제목 말(주장·판단 등)로 주체가 정해질 때만 자른다
      (나열 목록을 잘게 쪼개지 않는다).
    - 제목만 있는 위 단계 조각은 아래 조각 글 앞에 제목으로 붙으므로 따로 두지 않는다.
    """
    if not lines:
        raise PrecedentIndexError("【이 유】 아래 글이 없다")

    parts: list[_Part] = []
    used: set[str] = set()
    n1 = n2 = n3 = 0
    heads: list[str] = []
    cur: _Part | None = None

    def start(key: str, label: str, new_heads: list[str], first: str) -> None:
        nonlocal cur, heads
        if cur:
            parts.append(cur)
        base, k = key, 0
        while key in used:  # 같은 번호가 다시 맞춰진 경우 위치 키가 겹치지 않게
            k += 1
            key = f"{base}-d{k}"
        used.add(key)
        heads = new_heads
        cur = _Part(key, label, list(new_heads), [first])

    cur = _Part("r0-0", "이유", [], [])
    used.add("r0-0")
    for line in lines:
        short = len(line) <= _HEADING_MAX
        m1, m2, m3 = _LEVEL1.match(line), _LEVEL2.match(line), _LEVEL3.match(line)
        if m1 and (
            n1 == 0 or int(m1[1]) == n1 + 1 or (short and n1 <= int(m1[1]) <= n1 + _SKIP_MAX)
        ):
            n1, n2, n3 = int(m1[1]), 0, 0
            start(f"r{n1}-0", f"이유 {n1}.", [line], line)
        elif m2 and n1 and _level2_ok(m2[1], n2, short):
            n2, n3 = _HANGEUL_ORDER.index(m2[1]) + 1, 0
            start(f"r{n1}-{n2}", f"이유 {n1}. {m2[1]}.", [*heads[:1], line], line)
        elif m3 and n1 and short and classify_heading(line) is not None:
            n3 += 1
            above = heads[:2] if n2 else heads[:1]
            lead = f"이유 {n1}. {_HANGEUL_ORDER[n2 - 1]}." if n2 else f"이유 {n1}."
            start(f"r{n1}-{n2}-{n3}", f"{lead} {m3[1]}", [*above, line], line)
        else:
            cur.lines.append(line)
    parts.append(cur)

    result: list[_Part] = []
    for i, part in enumerate(parts):
        # 번호 앞 머리말이 "상고이유를 본다." 같은 한 마디뿐이면 검색할 내용이 없어 뺀다
        if part.key == "r0-0" and len("".join(part.lines)) < _PREAMBLE_MIN:
            continue
        nxt = parts[i + 1] if i + 1 < len(parts) else None
        # 제목 한 줄뿐인 조각은 바로 아래 조각이 그 제목을 이어받으므로 뺀다
        if nxt and len(part.lines) == 1 and len(part.heads) == len(nxt.heads) - 1:
            if nxt.heads[: len(part.heads)] == part.heads:
                continue
        result.append(part)
    return result


def _split_sentences(text: str, max_chars: int) -> list[str]:
    """한 줄이 max_chars보다 길 때 문장 끝(`.`)에서 자른다. 문장 하나가 더 길면 글자 수로 자른다."""
    pieces: list[str] = []
    cur = ""
    for sent in re.split(r"(?<=\.)\s+", text):
        while len(sent) > max_chars:  # 마침표 없이 긴 글 (드묾)
            if cur:
                pieces.append(cur)
                cur = ""
            pieces.append(sent[:max_chars])
            sent = sent[max_chars:]
        if cur and len(cur) + 1 + len(sent) > max_chars:
            pieces.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}" if cur else sent
    if cur:
        pieces.append(cur)
    return pieces


def pack_lines(lines: list[str], max_chars: int | None) -> list[list[str]]:
    """글(줄 목록)이 max_chars를 넘으면 줄(문단) 경계에서 묶음으로 나눈다. 안 넘으면 묶음 하나."""
    if not max_chars or len("\n".join(lines)) <= max_chars:
        return [lines]
    units: list[str] = []
    for ln in lines:
        units.extend(_split_sentences(ln, max_chars) if len(ln) > max_chars else [ln])
    groups: list[list[str]] = []
    cur: list[str] = []
    size = 0
    for u in units:
        add = len(u) + (1 if cur else 0)
        if cur and size + add > max_chars:
            groups.append(cur)
            cur, size = [u], len(u)
        else:
            cur.append(u)
            size += add
    groups.append(cur)
    return groups


def _make_chunk(
    index_version: str,
    doc_id: str,
    source_kind: str,
    kind: str,
    key: str,
    label: str,
    seq: int,
    text: str,
    decided: date | None,
    speaker: Speaker,
    attrs: dict,
) -> Chunk:
    return Chunk(
        chunk_id=f"{index_version}:{doc_id}:{key}",
        index_version=index_version,
        doc_id=doc_id,
        chunk_kind=kind,  # type: ignore[arg-type]
        location=Location(kind="paragraph", start=seq, end=seq, label=label),
        edition=_NOT_APPLICABLE,
        text=text,
        source_kind=source_kind,  # type: ignore[arg-type]
        decided_on=decided,
        speaker=speaker,
        attrs=dict(attrs),
    )


def _emit(
    out: list[Chunk],
    max_chars: int | None,
    key: str,
    label: str,
    lines: list[str],
    **fixed: Any,
) -> None:
    """조각 하나를 만든다. max_chars를 넘으면 문단 경계에서 잘라 `-p<n>` 키·`(n/m)` label로 낸다."""
    groups = pack_lines(lines, max_chars)
    for n, g in enumerate(groups, start=1):
        k, lb = (
            (key, label) if len(groups) == 1 else (f"{key}-p{n}", f"{label} ({n}/{len(groups)})")
        )
        out.append(_make_chunk(key=k, label=lb, seq=len(out) + 1, text="\n".join(g), **fixed))


def chunk_precedent(data: dict, index_version: str, max_chars: int | None = None) -> list[Chunk]:
    """판례 JSON(PrecService 하나) → 요지·전문 조각 목록. max_chars를 넘는 조각은 나눈다."""
    try:
        d = data["PrecService"]
        case_no = str(d["사건번호"]).strip()
    except KeyError, TypeError:
        raise PrecedentIndexError("판례 JSON에 PrecService.사건번호가 없다") from None
    if not case_no:
        raise PrecedentIndexError("판례 사건번호가 비었다")
    doc_id = f"판례_{case_no}"
    decided = _parse_date(d.get("선고일자"))
    if decided is None:
        logger.warning(
            "%s: 선고일자를 읽을 수 없어 decided_on=null (%r)", doc_id, d.get("선고일자")
        )
    fixed: dict[str, Any] = {
        "index_version": index_version,
        "doc_id": doc_id,
        "source_kind": "precedent",
        "decided": decided,
        "attrs": {
            "법원명": str(d.get("법원명") or "").strip(),
            "사건명": str(d.get("사건명") or "").strip(),
            "사건종류": str(d.get("사건종류명") or "").strip(),
        },
    }

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
                _emit(
                    chunks, max_chars, f"{prefix}{n}", label, part.split("\n"),
                    kind="judgment_summary", speaker="court", **fixed,
                )  # fmt: skip

    for part in split_reasons(str(d.get("판례내용") or "")):
        # 아래 단계 조각에는 위 단계 제목을 앞에 붙여 무슨 이야기인지 남긴다
        lines = [*part.heads[:-1], *part.lines] if len(part.heads) > 1 else part.lines
        _emit(
            chunks, max_chars, part.key, part.label, lines,
            kind="judgment", speaker=_speaker(part.heads), **fixed,
        )  # fmt: skip
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


def _is_break(text: str) -> bool:
    """이유가 끝나는 줄: [별지] 제목, 심판장·심판관 서명, 직인 번호 줄. 앞 줄에 잇지 않는다."""
    if _APPENDIX.match(text) or _SEAL_NUMBERS.match(text):
        return True
    return len(text) < _SIGN_MAX and _TRIAL_SIGN.search(text) is not None


def _trial_paragraphs(pages: list[str]) -> list[str]:
    """쪽 글 → 문단 목록. 쪽 번호 줄을 지우고, 줄바꿈으로 끊긴 문장을 공백으로 이어 붙인다.

    PDF마다 줄 사이에 빈 줄이 있기도 없기도 해서 빈 줄은 보지 않는다. 줄을 차례로 보며 앞 줄 끝이
    마침표 등이 아니면 같은 문장으로 보고 이어 붙인다 (쪽이 바뀌는 곳도 같다). 번호 제목 줄
    (`가. …`, `(1) …`)과 [별지]·서명·직인 번호 줄은 앞 줄에 잇지 않고, 그 아래 줄도 잇지 않는다.
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
            is_open = (
                len(prev) > 12
                and not prev.endswith(_PARA_END)
                and not _is_heading(prev)
                and not _is_break(prev)
            )
            if is_open and not _HEAD_MARK.match(b) and not _is_break(b):
                paras[-1] = f"{prev} {b}"
            else:
                paras.append(b)
    return paras


def chunk_trial(
    pages: list[str],
    file_name: str,
    index_version: str,
    trial_type: str | None = None,
    max_chars: int | None = None,
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

    # 이유 글은 첫 서명(심판장) 줄이나 [별지] 제목 줄 앞까지. 그 뒤(서명·청구항·도면)는 버린다
    rest = paras[start + 1 :]
    cut = next((i for i, p in enumerate(rest) if _is_break(p)), len(rest))
    body, dropped = rest[:cut], rest[cut:]
    while body and (body[-1] == "[" or _SEAL_NUMBERS.match(body[-1])):
        body.pop()  # 서명 위 직인 번호, 갈라진 "[별지" 앞 대괄호
    if dropped and not any(_APPENDIX.match(p) for p in dropped):
        if any("【청구항" in p for p in dropped):
            logger.warning("%s: [별지] 제목을 못 찾았는데 이유 뒤에 【청구항이 있다", doc_id)
    logger.info("%s: 이유 뒤 서명·별지 %d자를 버렸다", doc_id, sum(len(p) for p in dropped))

    fixed: dict[str, Any] = {
        "index_version": index_version,
        "doc_id": doc_id,
        "source_kind": "trial",
        "decided": decided,
        "attrs": {"결과": result, "유형": trial_type},
    }
    chunks: list[Chunk] = []
    for part in split_numbered(body):
        lines = [*part.heads[:-1], *part.lines] if len(part.heads) > 1 else part.lines
        # 판단 주체는 심판부 (judgment의 court와 같은 뜻으로 쓴다)
        _emit(
            chunks, max_chars, part.key, part.label, lines,
            kind="judgment", speaker=_speaker(part.heads), **fixed,
        )  # fmt: skip
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


def _max_chars(cfg: dict) -> int | None:
    v = cfg.get("max_chars")
    return int(v) if v else None


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
        chunks.extend(
            chunk_precedent(
                json.loads(p.read_text(encoding="utf-8")), index_version, _max_chars(cfg)
            )
        )
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
                read_trial_pages(pdf),
                pdf.name,
                index_version,
                pdf.parent.name.replace("_", "+"),
                _max_chars(cfg),
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
