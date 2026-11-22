"""쪽 줄 목록 → 조각 (design 3-2절). 한국 공보는 식별번호·청구항·요약·도면 설명, 논문은 쪽,
미국 공개공보는 문단 번호·청구항·요약.

식별번호가 없는 공보의 본문은 조각으로 만들지 않는다 (문단 번호를 지어내지 않음, 재아 11/19).
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from patent_ai.retrieval.cite_index.columns import (
    GrantedConfig,
    GrantedPage,
    is_drawing_sheet,
    load_granted_config,
)
from patent_ai.retrieval.cite_index.pages import PageText
from patent_ai.retrieval.schemas import Chunk, Edition, Location

DEFAULT_CONFIG = Path(__file__).resolve().parents[4] / "config" / "cite_search.yaml"

# 식별번호 줄 머리: [0023] / 【0023】
_MARKER = re.compile(r"^([\[【]\s*(\d{4})\s*[\]】])\s*(.*)$")
# 도면 번호 경계 (eval/retrieval/checks.py와 같다)
# 앞이 글자·숫자면 안 읽고, 뒤가 소수·℃·%·°면 안 읽는다
_FIG_HEAD = re.compile(r"(?<!\w)(?:도면|도)\s*(\d+)(?!\d|\.\d|[℃%°])([A-Za-z]?)")
_FIG_RANGE = re.compile(r"\s*(?:내지|~|-)\s*(?:도면|도)?\s*(\d+)(?!\d|\.\d|[℃%°])")
_FIG_AND = re.compile(r"\s*및\s*(?:도면|도)?\s*(\d+)(?!\d|\.\d|[℃%°])")
# 도면 설명 항목의 줄 머리 ("도 1은 …")
_FIG_START = re.compile(r"^(?:도면|도)\s*\d+(?!\d|\.\d|[℃%°])")
# 도면 쪽의 "도면1", "도면2a" 한 줄
_FIG_PAGE_LINE = re.compile(r"^도면\d+[A-Za-z]?$")
_CLAIM_HEAD = re.compile(r"^청구항\s*(\d+)\s*\.?$")


@dataclass
class ChunkingConfig:
    claims_heading: re.Pattern
    abstract_heading: re.Pattern
    rep_figure: re.Pattern
    figdesc_heading: re.Pattern
    section_headings: list[re.Pattern]

    @classmethod
    def from_dict(cls, cfg: dict) -> ChunkingConfig:
        # 설정 파일의 chunking 칸 -> 정규식. 색인 명령과 기본 경로가 이 하나만 쓴다
        return cls(
            claims_heading=re.compile(cfg["claims_heading"]),
            abstract_heading=re.compile(cfg["abstract_heading"]),
            rep_figure=re.compile(cfg["rep_figure"]),
            figdesc_heading=re.compile(cfg["figdesc_heading"]),
            section_headings=[re.compile(p) for p in cfg["section_headings"]],
        )


@lru_cache(maxsize=4)
def load_chunking_config(path: Path = DEFAULT_CONFIG) -> ChunkingConfig:
    return ChunkingConfig.from_dict(
        yaml.safe_load(Path(path).read_text(encoding="utf-8"))["chunking"]
    )


@dataclass
class UsChunkingConfig:
    abstract_heading: re.Pattern  # 공백을 빼고 대문자로 바꾼 줄에 맞춘다
    claims_heading: re.Pattern  # 대소문자 무시
    section_heading: re.Pattern
    inid_line: re.Pattern
    max_number_jump: int  # 문단 번호가 한 번에 이만큼보다 크게 뛰면 문단 번호가 아님

    @classmethod
    def from_dict(cls, cfg: dict) -> UsChunkingConfig:
        # 설정 파일의 us_chunking 칸 -> 정규식
        return cls(
            abstract_heading=re.compile(cfg["abstract_heading"]),
            claims_heading=re.compile(cfg["claims_heading"], re.IGNORECASE),
            section_heading=re.compile(cfg["section_heading"]),
            inid_line=re.compile(cfg["inid_line"]),
            max_number_jump=int(cfg["max_number_jump"]),
        )


@lru_cache(maxsize=4)
def load_us_chunking_config(path: Path = DEFAULT_CONFIG) -> UsChunkingConfig:
    return UsChunkingConfig.from_dict(
        yaml.safe_load(Path(path).read_text(encoding="utf-8"))["us_chunking"]
    )


def parse_figures(text: str) -> list[int]:
    """글 속 도면 번호: 도 3, 도 3a(→3), 도 3 내지 도 5·도 3-5(→3,4,5), 도 3 및 4."""
    out: list[int] = []
    for m in _FIG_HEAD.finditer(text):
        nums = [int(m.group(1))]
        pos = m.end()
        while True:
            r = _FIG_RANGE.match(text, pos)
            if r:
                hi = int(r.group(1))
                nums += list(range(nums[-1] + 1, hi + 1)) if 0 <= hi - nums[-1] <= 50 else [hi]
                pos = r.end()
                continue
            a = _FIG_AND.match(text, pos)
            if a:
                nums.append(int(a.group(1)))
                pos = a.end()
                continue
            break
        for n in nums:
            if n not in out:
                out.append(n)
    return out


def _chunk(doc_id, iv, key, kind, loc: Location, lines: list[str]) -> Chunk:
    return Chunk(
        chunk_id=f"{iv}:{doc_id}:{key}",
        index_version=iv,
        doc_id=doc_id,
        chunk_kind=kind,
        location=loc,
        edition=Edition(status="not_applicable"),
        text=" ".join(s.strip() for s in lines if s.strip()),
    )


@dataclass
class _Block:
    kind: str  # claim / abs / para / figraw
    lines: list[str] = field(default_factory=list)
    num: int | None = None
    label: str = ""
    page: int = 0
    in_figdesc: bool = False  # 도면 설명 구간 안의 문단이면 도면별 조각도 만든다
    figures: list[int] = field(default_factory=list)


class _KrChunker:
    def __init__(self, doc_id: str, iv: str, cfg: ChunkingConfig):
        self.doc_id, self.iv, self.cfg = doc_id, iv, cfg
        self.chunks: list[Chunk] = []
        self.warnings: list[str] = []
        self.seen: set[str] = set()
        self.n_paragraph = 0
        self.n_figure = 0  # 지금 도면 설명 구간에서 만든 도면 조각 수

    def _add(self, key, kind, loc, lines) -> None:
        if key in self.seen:
            # 같은 키가 또 나오면 앞의 것만 남긴다 (조각 ID 중복 방지)
            self.warnings.append(f"조각 키 중복: {self.doc_id} {key} 뒤의 것을 버림")
            return
        if not any(s.strip() for s in lines):
            self.warnings.append(f"빈 조각: {self.doc_id} {key}")
            return
        self.seen.add(key)
        self.chunks.append(_chunk(self.doc_id, self.iv, key, kind, loc, lines))

    def _figure_items(self, lines: list[str]) -> None:
        # 줄 머리가 "도 N"이면 새 도면 항목, 아니면 앞 항목에 이어 붙인다
        items: list[list[str]] = []
        for ln in lines:
            if _FIG_START.match(ln):
                items.append([ln])
            elif items:
                items[-1].append(ln)
        for item in items:
            m = _FIG_HEAD.match(item[0])
            figs = parse_figures(item[0]) or [int(m.group(1))]
            key = f"fig{m.group(1)}{m.group(2).lower()}"
            label = f"도 {m.group(1)}{m.group(2).lower()}"
            loc = Location(kind="figure", label=label, figures=figs)
            before = len(self.chunks)
            self._add(key, "figure_desc", loc, item)
            self.n_figure += len(self.chunks) - before

    def flush(self, b: _Block | None) -> None:
        if b is None:
            return
        if b.kind == "claim":
            loc = Location(kind="claim", label=b.label, claims=[b.num])
            self._add(f"claim{b.num}", "claim", loc, b.lines)
        elif b.kind == "abs":
            loc = Location(kind="abstract", label="요약", figures=b.figures)
            self._add("abs", "abstract", loc, b.lines)
        elif b.kind == "para":
            text = " ".join(b.lines)
            loc = Location(
                kind="paragraph",
                start=b.num,
                end=b.num,
                label=b.label,
                figures=parse_figures(text),
            )
            key = f"p{b.num:04d}"
            before = len(self.chunks)
            self._add(key, "body", loc, b.lines)
            if len(self.chunks) > before:
                self.n_paragraph += 1
                if b.in_figdesc:
                    self._figure_items(b.lines)
        elif b.kind == "figraw":
            self._figure_items(b.lines)

    def run(self, pages: list[PageText]) -> None:
        cfg = self.cfg
        cur: _Block | None = None
        claims_mode = False  # 청구항 구간 (머리 줄 전의 글자는 버림)
        last_claim = 0
        in_figdesc = False
        pending_rep: list[int] = []
        markers_seen = 0

        for page in pages:
            for raw in page.lines:
                s = raw.strip()
                if not s:
                    continue
                norm = re.sub(r"\s+", "", s)
                # 요약은 첫 쪽 안에서만 (쪽이 바뀌면 끝)
                if cur and cur.kind == "abs" and page.page != cur.page:
                    self.flush(cur)
                    cur = None
                if _FIG_PAGE_LINE.match(norm):
                    self.flush(cur)
                    cur, claims_mode, in_figdesc = None, False, False
                    continue
                if cfg.claims_heading.match(norm):
                    self.flush(cur)
                    cur, claims_mode, last_claim, in_figdesc = None, True, 0, False
                    continue
                if cfg.abstract_heading.match(norm):
                    self.flush(cur)
                    cur = _Block("abs", page=page.page, figures=list(pending_rep))
                    pending_rep = []
                    claims_mode, in_figdesc = False, False
                    continue
                rep = cfg.rep_figure.match(norm)
                if rep:
                    if cur and cur.kind == "abs":
                        cur.figures = [int(rep.group(1))]
                        self.flush(cur)
                        cur = None
                    else:
                        pending_rep = [int(rep.group(1))]
                    continue
                if cfg.figdesc_heading.match(norm):
                    self.flush(cur)
                    cur = _Block("figraw")
                    claims_mode, in_figdesc = False, True
                    self.n_figure = 0
                    continue
                if any(h.match(norm) for h in cfg.section_headings):
                    self.flush(cur)
                    cur, claims_mode, in_figdesc = None, False, False
                    continue
                m = _MARKER.match(s)
                if m:
                    self.flush(cur)
                    markers_seen += 1
                    rest = m.group(3).strip()
                    # 도면 항목이 이미 나온 뒤에 도면이 아닌 문단이 오면 도면 설명 끝
                    # (그 전의 머리 문단은 "첨부 도면은 …" 같은 안내라 구간에 남긴다)
                    if in_figdesc and self.n_figure > 0 and not _FIG_START.match(rest):
                        in_figdesc = False
                    cur = _Block(
                        "para",
                        lines=[rest] if rest else [],
                        num=int(m.group(2)),
                        label=m.group(1),
                        in_figdesc=in_figdesc,
                    )
                    claims_mode = False
                    continue
                if claims_mode:
                    c = _CLAIM_HEAD.match(s)
                    if c and int(c.group(1)) > last_claim:
                        self.flush(cur)
                        last_claim = int(c.group(1))
                        cur = _Block("claim", num=last_claim, label=f"청구항 {last_claim}")
                    elif cur and cur.kind == "claim":
                        cur.lines.append(s)
                    continue
                if cur is not None:
                    cur.lines.append(s)
        self.flush(cur)
        if markers_seen == 0:
            self.warnings.append("식별번호 없음: 본문 조각 안 만듦")


def _chunk_paper(doc_id: str, pages: list[PageText], iv: str) -> tuple[list[Chunk], list[str]]:
    chunks, warns = [], []
    for p in pages:
        if not any(ln.strip() for ln in p.lines):
            warns.append(f"글자 없는 쪽: {doc_id} {p.page}쪽")
            continue
        loc = Location(kind="page", start=p.page, end=p.page, label=f"{p.page}쪽")
        chunks.append(_chunk(doc_id, iv, f"pg{p.page}", "body", loc, p.lines))
    return chunks, warns


# --- 미국 공개공보 ---
# 문단 번호 줄 머리. OCR이 "["를 1·I·l·| 로, "]"를 ) 등으로, "0"을 O로 읽기도 한다.
# 닫는 괄호가 있는 꼴: [0025] / [0 025 ] / 10025 ] (숫자 사이 공백 허용)
_US_NUM_CLOSED = re.compile(
    r"^[\[【(\{|Il1]?\s*([0-9Oo](?:\s?[0-9Oo]){3})\s*[\]】)\}|]\s*\.?\s*(.*)$"
)
# 닫는 괄호가 없는 꼴: 0025 Text / 0025. Text / I0025. Text / (0025 Text
_US_NUM_BARE = re.compile(r"^[\[【(\{|Il]?\s*([0-9Oo]{4})\.?\s+(\S.*)$")
_US_CLAIM_ONE = re.compile(r"^1\s?\.\s+\S")
_US_CLAIM_LINE = re.compile(r"^(\d{1,3})\s?\.\s+(\S.*)$")
# 도면 번호: FIG. 3 / FIG. 3A / FIGS. 3 and 4 / FIGS. 3-5 · 3 to 5 · 3 through 5
_US_FIG_HEAD = re.compile(
    r"(?<![A-Za-z])FIG(?:URE)?S?\.?\s*(\d+)(?!\d|\.\d)[A-Za-z]?", re.IGNORECASE
)
_US_FIG_RANGE = re.compile(
    r"\s*(?:-|–|to|through)\s*(?:FIG(?:URE)?S?\.?\s*)?(\d+)(?!\d|\.\d)[A-Za-z]?", re.IGNORECASE
)
_US_FIG_AND = re.compile(
    r"\s*(?:and|&)\s*(?:FIG(?:URE)?S?\.?\s*)?(\d+)(?!\d|\.\d)[A-Za-z]?", re.IGNORECASE
)


def us_paragraph_number(line: str) -> tuple[int, str] | None:
    """줄 머리의 문단 번호 → (번호, 나머지 글). 네 자리가 아니거나 0이면 None.

    표지의 연도·번호(4321 …)도 후보로 읽힌다. 걸러내는 건 longest_increasing이다.
    """
    s = line.strip()
    m = _US_NUM_CLOSED.match(s)
    bare = False
    if not m:
        m = _US_NUM_BARE.match(s)
        bare = True
    if not m:
        return None
    digits = re.sub(r"\s", "", m.group(1))
    # 닫는 괄호가 없는 꼴은 진짜 숫자가 하나는 있어야 한다 ("Oooo" 같은 낱말 방지)
    if bare and not any(c.isdigit() for c in digits):
        return None
    num = int(digits.replace("O", "0").replace("o", "0"))
    if num < 1:
        return None
    return num, m.group(2).strip()


def longest_increasing(nums: list[int], max_jump: int | None = None) -> list[int]:
    """가장 긴 '엄격하게 늘어나는' 부분수열의 위치(index) 목록. O(n²).

    max_jump가 있으면 첫 번호와 이어지는 걸음(앞 번호와의 차이)이 모두 max_jump 이하여야 한다
    (본문 속 "1102 is coupled", "1000 degrees" 같은 큰 수가 문단 번호로 읽히는 것을 막는다).
    같은 길이가 여럿이면 정해진 규칙: 앞 번호는 길이가 같은 것 중 가장 뒤 위치, 끝은 가장 앞 위치.
    같은 입력이면 늘 같은 결과.
    """
    n = len(nums)
    length = [0] * n  # 0 = 이 번호는 수열에 못 들어감
    prev = [-1] * n
    for j in range(n):
        if max_jump is None or nums[j] <= max_jump:
            length[j] = 1
        for i in range(j):
            if not length[i] or nums[i] >= nums[j]:
                continue
            if max_jump is not None and nums[j] - nums[i] > max_jump:
                continue
            if length[i] + 1 >= length[j]:  # 같으면 더 뒤의 i가 이긴다
                length[j], prev[j] = length[i] + 1, i
    best = max(length, default=0)
    if best == 0:
        return []
    i = length.index(best)  # 가장 앞 위치의 끝
    out: list[int] = []
    while i != -1:
        out.append(i)
        i = prev[i]
    return out[::-1]


def parse_us_figures(text: str) -> list[int]:
    """글 속 도면 번호: FIG. 3, FIG. 3A(→3), FIGS. 3 and 4, FIGS. 3-5·3 to 5(→3,4,5)."""
    out: list[int] = []
    for m in _US_FIG_HEAD.finditer(text):
        nums = [int(m.group(1))]
        pos = m.end()
        while True:
            r = _US_FIG_RANGE.match(text, pos)
            if r:
                hi = int(r.group(1))
                nums += list(range(nums[-1] + 1, hi + 1)) if 0 <= hi - nums[-1] <= 50 else [hi]
                pos = r.end()
                continue
            a = _US_FIG_AND.match(text, pos)
            if a:
                nums.append(int(a.group(1)))
                pos = a.end()
                continue
            break
        for n in nums:
            if n not in out:
                out.append(n)
    return out


class _UsChunker:
    """미국 공개공보(A1·A2·A9) 한 건. 요약 → 문단 번호 확정 → 본문·청구항 순으로 훑는다."""

    def __init__(self, doc_id: str, iv: str, cfg: UsChunkingConfig):
        self.doc_id, self.iv, self.cfg = doc_id, iv, cfg
        self.chunks: list[Chunk] = []
        self.warnings: list[str] = []
        self.seen: set[str] = set()
        self.check: dict = {}
        self.dropped = 0  # 조각에 못 든 줄 수 (조용히 버리지 않고 센다)

    def _add(self, key, kind, loc, lines) -> bool:
        # 한국 청커와 같다: 같은 키는 앞의 것만, 빈 조각은 만들지 않고 경고
        if key in self.seen:
            self.warnings.append(f"조각 키 중복: {self.doc_id} {key} 뒤의 것을 버림")
            self.dropped += sum(1 for s in lines if s.strip())
            return False
        if not any(s.strip() for s in lines):
            self.warnings.append(f"빈 조각: {self.doc_id} {key}")
            return False
        self.seen.add(key)
        self.chunks.append(_chunk(self.doc_id, self.iv, key, kind, loc, lines))
        return True

    def _flush_para(self, num: int | None, lines: list[str]) -> None:
        if num is None:
            return
        loc = Location(
            kind="paragraph",
            start=num,
            end=num,
            label=f"[{num:04d}]",
            figures=parse_us_figures(" ".join(lines)),
        )
        self._add(f"p{num:04d}", "body", loc, lines)

    def _flush_claim(self, num: int | None, lines: list[str]) -> None:
        if num is None:
            return
        loc = Location(kind="claim", label=f"청구항 {num}", claims=[num])
        self._add(f"claim{num}", "claim", loc, lines)

    def _abstract(self, flat: list[tuple[int, str]]) -> set[int]:
        """요약 조각을 만들고 쓴 줄 위치를 돌려준다. 제목 뒤 맨 앞 빈 줄은 건너뛴다."""
        cfg = self.cfg
        used: set[int] = set()
        for i, (pg, s) in enumerate(flat):
            if not (s and cfg.abstract_heading.match(re.sub(r"\s+", "", s).upper())):
                continue
            used.add(i)
            body: list[str] = []
            for j in range(i + 1, len(flat)):
                pj, sj = flat[j]
                if pj != pg or cfg.inid_line.match(sj):
                    break
                if not sj:
                    if body:  # 글이 한 줄 이상 나온 뒤의 빈 줄이 요약의 끝
                        break
                    continue
                body.append(sj)
                used.add(j)
            if body:
                text = " ".join(body)
                loc = Location(kind="abstract", label="요약", figures=parse_us_figures(text))
                self._add("abs", "abstract", loc, body)
            break
        if "abs" not in self.seen:
            self.warnings.append(f"요약 없음: {self.doc_id}")
        return used

    @staticmethod
    def _claim_start(flat: list[tuple[int, str]], frm: int, end: int) -> tuple[int, int] | None:
        """frm 이후에서 청구항이 시작되는 (줄 위치, 첫 청구항 번호).

        "1. …" 줄이 있으면 거기서 시작. 없으면 번호 n 줄이 있고 뒤에 n+1 줄이 또 있는 첫 줄
        (앞 청구항이 글자층에 없는 문헌)."""
        for i in range(frm, end):
            if _US_CLAIM_ONE.match(flat[i][1]):
                return i, 1
        for i in range(frm, end):
            m = _US_CLAIM_LINE.match(flat[i][1])
            if m and int(m.group(1)) > 1:
                nxt = int(m.group(1)) + 1
                for j in range(i + 1, end):
                    m2 = _US_CLAIM_LINE.match(flat[j][1])
                    if m2 and int(m2.group(1)) == nxt:
                        return i, int(m.group(1))
        return None

    def run(self, pages: list[PageText]) -> None:
        cfg = self.cfg
        flat = [(p.page, ln.strip()) for p in pages for ln in p.lines]
        used = self._abstract(flat)  # 요약으로 쓴 줄은 문단 후보에서 뺀다
        n = len(flat)

        # 1) 청구항 머리 줄이 있으면 그 앞 줄만 문단 번호 후보
        head = next(
            (i for i in range(n) if i not in used and cfg.claims_heading.match(flat[i][1])), None
        )
        cand_end = head if head is not None else n

        # 2) 문단 번호 후보 중 번호 점프가 작게 늘어나는 것만 진짜로 본다
        cands: list[tuple[int, int, str]] = []  # (줄 위치, 번호, 나머지 글)
        for i in range(cand_end):
            if i in used or not flat[i][1]:
                continue
            r = us_paragraph_number(flat[i][1])
            if r:
                cands.append((i, r[0], r[1]))
        keep = longest_increasing([c[1] for c in cands], cfg.max_number_jump)
        accepted = {cands[k][0]: (cands[k][1], cands[k][2]) for k in keep}
        nums = sorted(v[0] for v in accepted.values())
        last = nums[-1] if nums else None
        first_line = min(accepted) if accepted else n
        last_line = max(accepted) if accepted else -1
        # 첫 문단 앞의 후보(표지 숫자)는 경고 없이 세기만, 첫~끝 사이에서 버린 것은 경고
        skipped_before_first = sum(1 for c in cands if c[0] < first_line)
        out_of_order = sum(
            1 for c in cands if first_line < c[0] < last_line and c[0] not in accepted
        )
        # 마지막 확정 번호 뒤에서 튄 후보: 글자는 앞 문단에 남지만 조용히 두지 않고 센다
        # (확정 번호가 0개면 모든 후보가 표지 숫자 쪽에 이미 세졌으니 0)
        after_last = sum(1 for c in cands if c[0] > last_line) if accepted else 0

        # 3) 청구항 시작 위치
        claims_idx: int | None = None  # 청구항 구간 첫 줄 (머리 줄이거나 첫 청구항 줄)
        first_claim = 1
        # 청구항 머리 줄이 있으면 문단 번호가 하나도 없어도 청구항은 만든다
        if head is not None:
            found = self._claim_start(flat, head + 1, n)
            claims_idx = head
            if found:
                first_claim = found[1]
        elif accepted:
            found = self._claim_start(flat, last_line + 1, n)
            if found:
                claims_idx, first_claim = found
        claims_found = False

        def after_heading_run(i: int) -> int | None:
            # 제목 줄 i 뒤로 이어지는 대문자 제목 줄(두 줄로 꺾인 제목)을 건너뛰고
            # 처음 나오는 다른 줄의 위치. 문단 번호·청구항 시작 줄이면 거기서 멈춘다
            for j in range(i + 1, n):
                if j in accepted or j == claims_idx:
                    return j
                if flat[j][1] and not cfg.section_heading.match(flat[j][1]):
                    return j
            return None

        # 4) 본문과 청구항을 한 번에 훑는다
        cur_num: int | None = None
        cur_lines: list[str] = []
        claim_no: int | None = None
        claim_lines: list[str] = []
        expected = first_claim
        for i in range(first_line if accepted else (head if head is not None else n), n):
            s = flat[i][1]
            if i in used or not s:
                continue
            if i in accepted:
                self._flush_para(cur_num, cur_lines)
                cur_num, rest = accepted[i]
                cur_lines = [rest] if rest else []
                continue
            if claims_idx is not None and i >= claims_idx:
                if i == claims_idx and head is not None:
                    self._flush_para(cur_num, cur_lines)
                    cur_num, cur_lines = None, []
                    continue  # 청구항 머리 줄은 버린다 (제목이라 센 줄 아님)
                if i == claims_idx:  # 머리 줄 없이 "1. A …" 줄에서 시작
                    self._flush_para(cur_num, cur_lines)
                    cur_num, cur_lines = None, []
                c = _US_CLAIM_LINE.match(s)
                if c and int(c.group(1)) == expected:
                    self._flush_claim(claim_no, claim_lines)
                    claim_no, claim_lines = expected, [c.group(2)]
                    expected += 1
                    claims_found = True
                elif claim_no is not None:
                    claim_lines.append(s)
                else:
                    self.dropped += 1  # 첫 청구항 전의 줄
                continue
            # 본문 구간. 대문자 제목처럼 보여도 바로 뒤가 문단 번호나 청구항 시작일 때만 제목
            if cfg.section_heading.match(s):
                nx = after_heading_run(i)
                if nx is not None and (nx in accepted or nx == claims_idx):
                    self._flush_para(cur_num, cur_lines)
                    cur_num, cur_lines = None, []
                    continue
            if cur_num is not None:
                cur_lines.append(s)
            else:
                self.dropped += 1
        self._flush_para(cur_num, cur_lines)
        self._flush_claim(claim_no, claim_lines)

        # 5) 검사 결과와 경고
        missing = len(set(range(1, (last or 0) + 1)) - set(nums))
        self.check = {
            "last": last,
            "accepted": len(nums),
            "missing": missing,
            "out_of_order": out_of_order,
            "after_last": after_last,
            "skipped_before_first": skipped_before_first,
            "dropped_lines": self.dropped,
        }
        if last is None:
            self.warnings.append("문단 번호 없음: 본문 조각 안 만듦")
            if head is None:
                return  # 청구항 머리도 없으면 청구항 경고는 없다
        if missing:
            self.warnings.append(f"문단 번호 빠짐: {self.doc_id} {missing}개 (1~{last})")
        if out_of_order:
            self.warnings.append(
                f"문단 번호 역순·튐 무시: {self.doc_id} {out_of_order}개 (본문 글자로 둠)"
            )
        if after_last:
            self.warnings.append(
                f"문단 번호 끝 뒤 튐 무시: {self.doc_id} {after_last}개 (앞 문단 글자로 둠)"
            )
        if not claims_found:
            self.warnings.append(f"청구항 시작 못 찾음: {self.doc_id}")
        elif first_claim > 1:
            self.warnings.append(f"청구항 1~{first_claim - 1} 글자층에 없음: {self.doc_id}")
        if self.dropped:
            self.warnings.append(f"버린 줄: {self.doc_id} {self.dropped}개")


_US_APPLICATION = re.compile(r"^US\d+A[129]$")
# 등록공보: B1·B2·B, 또는 옛 번호 A (숫자 8자리 이하, 공개공보 A1은 아님)
_US_GRANTED = re.compile(r"^US(?:\d+B[12]?|\d{1,8}A)$")


def is_granted_doc(doc_id: str) -> bool:
    return bool(_US_GRANTED.match(doc_id))


def chunk_granted(
    doc_id: str,
    pages: list[GrantedPage],
    iv: str,
    us_cfg: UsChunkingConfig,
    cfg: GrantedConfig,
) -> tuple[list[Chunk], list[str], dict | None]:
    """미국 등록공보: 본문 쪽을 칼럼·줄 창으로 자른다. 줄을 센 쪽이 하나도 없으면 쪽 조각."""
    # 칼럼 배치가 없는 쪽(PageText 등)은 줄을 못 센 쪽으로 본다
    text_pages = [p for p in pages if getattr(p, "columns", None) is not None]
    if not text_pages:
        chunks, warns = _chunk_paper(doc_id, pages, iv)
        warns.append(f"칼럼·줄 못 셈: {doc_id} page 조각으로")
        return chunks, warns, None

    u = _UsChunker(doc_id, iv, us_cfg)
    # 요약은 1쪽(표지) 줄에서 찾는다
    u._abstract([(p.page, ln.strip()) for p in pages if p.page == 1 for ln in p.lines])

    # 칼럼 번호: 인쇄된 번호를 쓴다 (왼쪽, 없으면 오른쪽 - 1). 둘 다 못 읽으면 앞 본문 쪽 왼쪽 + 2
    # (그 사이 못 센 본문 쪽이 있으면 그만큼 더 건너뛴다). 첫 본문 쪽은 못 읽으면 1.
    # 기대 번호와 인쇄 번호가 다르면 개수만 세서 경고한다.
    mismatch = uncounted = reused = 0
    prev_left: int | None = None
    gap = 0  # 앞 본문 쪽 뒤로 못 센 본문 쪽 수
    seen_text = False
    for p in pages:
        lay = getattr(p, "columns", None)
        if lay is None:
            # 첫 본문 쪽 뒤의 글자 있는 쪽 중 도면 쪽(Sheet N of M)이 아닌 것 = 못 센 본문 쪽
            has_text = any(ln.strip() for ln in p.lines)
            if seen_text and has_text and not is_drawing_sheet(p.lines[0] if p.lines else ""):
                uncounted += 1
                gap += 1
                loc = Location(kind="page", start=p.page, end=p.page, label=f"{p.page}쪽")
                u._add(f"pg{p.page}", "body", loc, p.lines)
                u.warnings.append(f"본문 쪽 줄 못 셈: {doc_id} {p.page}쪽 page 조각으로")
            continue
        seen_text = True
        reused += 1 if lay.reused else 0
        expected = prev_left + 2 * (gap + 1) if prev_left is not None else None
        pl, pr = lay.printed
        if pl is not None:
            left_no = pl
        elif pr is not None:
            left_no = pr - 1
        else:
            left_no = expected if expected is not None else 1
        if expected is not None:
            for printed, want in ((pl, expected), (pr, expected + 1)):
                if printed is not None and printed != want:
                    mismatch += 1
        prev_left, gap = left_no, 0
        for col, rows in ((left_no, lay.left), (left_no + 1, lay.right)):
            # 줄 번호 창으로 묶는다 (1~15, 16~30, ...)
            windows: dict[int, list[tuple[int, str]]] = {}
            for n, text in rows:
                windows.setdefault((n - 1) // cfg.lines_per_chunk, []).append((n, text))
            for w in sorted(windows):
                items = windows[w]
                lo, hi = items[0][0], items[-1][0]
                label = f"{col}:{lo}-{hi}"
                body = [t for _, t in items]
                loc = Location(
                    kind="column_line",
                    start=col * 10000 + lo,  # 정렬 키: 칼럼 x 10000 + 줄 (design 5-1)
                    end=col * 10000 + hi,
                    label=label,
                    figures=parse_us_figures(" ".join(body)),
                )
                u._add(label, "body", loc, body)
    if mismatch:
        u.warnings.append(f"칼럼 번호 불일치: {doc_id} {mismatch}개 (인쇄 번호와 앞 쪽 + 2가 다름)")
    check = {
        "text_pages": len(text_pages),
        "reused_fit_pages": reused,  # 여백 숫자가 모자라 앞 쪽 맞춤을 다시 쓴 쪽
        "uncounted_text_pages": uncounted,  # 끝내 못 세서 page 조각이 된 본문 쪽
        "skipped_pages": len(pages) - len(text_pages) - uncounted,
        "column_number_mismatch": mismatch,
        "max_residual": max(p.columns.max_residual for p in text_pages),
    }
    return u.chunks, u.warnings, check


def chunk_document_checked(
    doc_id: str,
    pages: list[PageText],
    index_version: str,
    config: ChunkingConfig | None = None,
    us_config: UsChunkingConfig | None = None,
    granted_config: GrantedConfig | None = None,
) -> tuple[list[Chunk], list[str], dict | None]:
    """chunk_document + 검사 결과 (공개공보는 문단 번호, 등록공보는 칼럼·줄. 나머지는 None)."""
    check: dict | None = None
    if is_granted_doc(doc_id):
        chunks, warns, check = chunk_granted(
            doc_id,
            pages,
            index_version,
            us_config or load_us_chunking_config(),
            granted_config or load_granted_config(),
        )
    elif doc_id.startswith("NPL-"):
        chunks, warns = _chunk_paper(doc_id, pages, index_version)
    elif doc_id.startswith("KR"):
        k = _KrChunker(doc_id, index_version, config or load_chunking_config())
        k.run(pages)
        chunks, warns = k.chunks, k.warnings
    elif _US_APPLICATION.match(doc_id):
        u = _UsChunker(doc_id, index_version, us_config or load_us_chunking_config())
        u.run(pages)
        chunks, warns, check = u.chunks, u.warnings, u.check
    elif doc_id.startswith("US"):
        return [], [f"지원 안 함: {doc_id} (미국 번호 꼴을 모름)"], None
    else:
        return [], [f"지원 안 함: {doc_id} (KR·US·NPL- 만 지원)"], None
    if not chunks:
        warns.append(f"조각 0개: {doc_id}")
    return chunks, warns, check


def chunk_document(
    doc_id: str,
    pages: list[PageText],
    index_version: str,
    config: ChunkingConfig | None = None,
    us_config: UsChunkingConfig | None = None,
) -> tuple[list[Chunk], list[str]]:
    """문헌 하나의 쪽 목록을 조각으로 나눈다. 나라는 doc_id 앞 글자로 정한다."""
    chunks, warns, _ = chunk_document_checked(doc_id, pages, index_version, config, us_config)
    return chunks, warns
