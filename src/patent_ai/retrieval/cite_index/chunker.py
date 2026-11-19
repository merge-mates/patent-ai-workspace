"""쪽 줄 목록 → 조각 (design 3-2절). 한국 공보는 식별번호·청구항·요약·도면 설명, 논문은 쪽.

식별번호가 없는 공보의 본문은 조각으로 만들지 않는다 (문단 번호를 지어내지 않음, 재아 11/19).
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

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


@lru_cache(maxsize=4)
def load_chunking_config(path: Path = DEFAULT_CONFIG) -> ChunkingConfig:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["chunking"]
    return ChunkingConfig(
        claims_heading=re.compile(cfg["claims_heading"]),
        abstract_heading=re.compile(cfg["abstract_heading"]),
        rep_figure=re.compile(cfg["rep_figure"]),
        figdesc_heading=re.compile(cfg["figdesc_heading"]),
        section_headings=[re.compile(p) for p in cfg["section_headings"]],
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


def chunk_document(
    doc_id: str,
    pages: list[PageText],
    index_version: str,
    config: ChunkingConfig | None = None,
) -> tuple[list[Chunk], list[str]]:
    """문헌 하나의 쪽 목록을 조각으로 나눈다. 나라는 doc_id 앞 글자로 정한다."""
    if doc_id.startswith("NPL-"):
        chunks, warns = _chunk_paper(doc_id, pages, index_version)
    elif doc_id.startswith("KR"):
        k = _KrChunker(doc_id, index_version, config or load_chunking_config())
        k.run(pages)
        chunks, warns = k.chunks, k.warnings
    else:
        return [], [f"지원 안 함: {doc_id} (KR·NPL- 만 지원)"]
    if not chunks:
        warns.append(f"조각 0개: {doc_id}")
    return chunks, warns
