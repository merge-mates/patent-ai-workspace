"""심사기준 청커: 심사기준 PDF 8판 × 세 장 → 법령 색인 조각 JSONL (이슈 #24 24b, design 5-1).

정한 것:
- 글자 뽑기는 `pdftotext -layout`(poppler). 실제 판에서 pdfplumber와 견줬다.
  pdfplumber는 문단 사이 빈 줄이 없어지고 쪽당 약 10배 느리다. pdftotext는 빈 줄이 남는다.
- 장 범위는 쪽 맨 위 줄(장 제목 `제3장 진보성`)과 맨 아래 줄 인쇄 쪽 번호(`3301` = 3부 3장 01쪽)로
  찾는다. 장 제목이 없거나 번호가 안 맞으면 오류 (빈 판으로 넘어가지 않는다).
- 절 번호(`6.4.1`)는 글자에 있는 판에서만 읽는다. 변환본 2판과 제124호는 절 제목이 그림이라
  글자에 없다. 그 판은 절 없이 쪽 단위 조각이 된다 (loc_label에 절 번호가 빠짐).
- 조각 = (쪽, 절). 절 하나가 두 쪽에 걸치면 쪽마다 조각 하나. 쪽 머리말(`제3부 특허요건`)과
  꼬리말(쪽 번호, `(2018년 1월 추록)`)은 버린다.
- doc_id = `심사기준_<예규번호>_<시행일>`, chunk_id = `<판>:<doc_id>:<인쇄 쪽 번호>-<쪽 안 순번>`.

실행: uv run python -m patent_ai.retrieval.guideline_index --config config/index/guidelines.yaml
"""

import argparse
import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import yaml

from patent_ai.db.models.chunks import check_law_chunk
from patent_ai.index_version import is_index_version
from patent_ai.retrieval.cite_index.pages import PageText
from patent_ai.retrieval.errors import RetrievalError
from patent_ai.retrieval.schemas import Chunk, Edition, Location

logger = logging.getLogger(__name__)

# 쪽 맨 위 머리말: `제3부 특허요건`(부 머리) 또는 `제3장 진보성`(장 머리)
_HEADER = re.compile(r"^제\s*(\d)\s*([부장])\s*(\S.*)$")
# 쪽 맨 아래: 인쇄 쪽 번호 네 자리. 앞뒤에 `(2018년 1월 추록)`이 붙기도 한다
_FOOTER = re.compile(r"^(?:\([^)]*추록\)\s*)?(\d{4})(?:\s*\([^)]*추록\))?$")
# 절 제목: 맨 앞 칸에서 시작하는 `1.`, `3.1`, `6.4.3.` 뒤에 짧은 제목
_SECTION = re.compile(r"^(\d{1,2}(?:\.\d{1,2})*)\.?\s+(\S.{0,58})$")
_MAX_HEADING_CHARS = 60


class GuidelineIndexError(RetrievalError):
    """심사기준 색인을 만들 수 없다 (장을 못 찾음, 원본 없음, 덮어쓰기 등)."""


@dataclass(frozen=True)
class Chapter:
    """심사기준 장 하나. 예: 제3부 제3장 진보성."""

    part: int
    chapter: int
    title: str

    @property
    def label(self) -> str:
        return f"제{self.part}부 제{self.chapter}장"

    @property
    def page_prefix(self) -> int:
        # 인쇄 쪽 번호 앞 두 자리 (3부 3장 → 33)
        return self.part * 10 + self.chapter


@dataclass(frozen=True)
class _Frame:
    header: str | None  # 쪽 맨 위 줄 (없으면 None)
    body: list[str]  # 머리·꼬리말을 뺀 줄 (들여쓰기 그대로)
    number: int | None  # 인쇄 쪽 번호 (못 읽으면 None)


def _frame(page: PageText) -> _Frame:
    """한 쪽을 머리말·본문·꼬리말로 가른다."""
    lines = list(page.lines)
    first = next((i for i, ln in enumerate(lines) if ln.strip()), None)
    if first is None:
        return _Frame(None, [], None)
    header = None
    if _HEADER.match(lines[first].strip()):
        header = lines[first].strip()
        lines = lines[first + 1 :]
    number = None
    # 아래에서 빈 줄을 건너뛰고 꼬리말 한 줄을 뗀다
    while lines and not lines[-1].strip():
        lines.pop()
    if lines:
        m = _FOOTER.match(lines[-1].strip())
        if m:
            number = int(m.group(1))
            lines.pop()
    return _Frame(header, lines, number)


def _is_chapter_header(header: str | None, chapter: Chapter) -> bool:
    if header is None:
        return False
    m = _HEADER.match(header)
    return bool(
        m
        and m.group(2) == "장"
        and m.group(1) == str(chapter.chapter)
        and m.group(3) == chapter.title
    )


def chapter_pages(pages: list[PageText], chapter: Chapter) -> range:
    """장 제목으로 찾은 쪽 범위 (PDF 쪽 번호 `PageText.page`, 끝 쪽 포함). 못 찾으면 오류.

    첫 쪽: 맨 위 줄이 장 제목이고 인쇄 쪽 번호가 그 장 번호(3부 3장 → 33xx)인 첫 쪽.
    끝 쪽: 첫 쪽부터 인쇄 쪽 번호가 다른 장 번호로 바뀌기 직전 쪽 (번호 없는 쪽은 안 끊는다).
    """
    frames = [(p.page, _frame(p)) for p in pages]
    start = next(
        (
            i
            for i, (_, f) in enumerate(frames)
            if _is_chapter_header(f.header, chapter)
            and f.number is not None
            and f.number // 100 == chapter.page_prefix
        ),
        None,
    )
    if start is None:
        raise GuidelineIndexError(f"장 제목을 못 찾았다: {chapter.label} {chapter.title}")
    end = start
    for i in range(start + 1, len(frames)):
        n = frames[i][1].number
        if n is not None and n // 100 != chapter.page_prefix:
            break
        end = i
    return range(frames[start][0], frames[end][0] + 1)


def _section_of(line: str) -> tuple[tuple[int, ...], str] | None:
    """맨 앞 칸에서 시작하는 절 제목 줄이면 (번호 튜플, 제목), 아니면 None."""
    if line[:1].isspace() or len(line) > _MAX_HEADING_CHARS:
        return None
    m = _SECTION.match(line.rstrip())
    if not m or "추록" in line:
        return None
    nums = tuple(int(x) for x in m.group(1).split("."))
    # 한 단계 번호는 점이 꼭 있어야 한다 ("2 이상의 항…" 같은 글 줄 시작을 거른다)
    if len(nums) == 1 and not re.match(r"^\d{1,2}\.", line):
        return None
    return nums, line.strip()


def _follows(prev: tuple[int, ...] | None, cur: tuple[int, ...]) -> bool:
    """절 번호가 앞 절 다음으로 말이 되나 (본문 줄 앞의 `1.5 배` 같은 숫자를 거른다)."""
    if prev is None:
        return cur == (1,)  # 장의 첫 절은 `1.`부터
    depth = len(cur)
    if depth == 1:
        return cur[0] == prev[0] + 1
    if prev[: depth - 1] != cur[:-1]:
        return False  # 부모가 다르다
    if len(prev) == depth - 1:
        return cur[-1] == 1  # 부모 바로 아래 첫 자식
    return cur[-1] == prev[depth - 1] + 1  # 바로 다음 형제


def _paragraphs(lines: list[str]) -> str:
    """줄 목록 → 글. 빈 줄이 문단 경계, 문단 안 줄은 공백 하나로 잇는다."""
    paras: list[str] = []
    cur: list[str] = []
    for ln in lines:
        if ln.strip():
            cur.append(ln.strip())
        elif cur:
            paras.append(" ".join(cur))
            cur = []
    if cur:
        paras.append(" ".join(cur))
    return "\n".join(paras)


def _loc_label(page_no: int, chapter: Chapter, section: str | None, converted: bool) -> str:
    where = f"{chapter.label} {section}" if section else chapter.label
    if converted:
        return f"{page_no}쪽 (변환본 쪽, {where})"
    return f"{page_no}쪽 ({where})"


def chunk_guideline(
    pages: list[PageText],
    doc_id: str,
    edition: Edition,
    index_version: str,
    chapter: Chapter,
    converted: bool = False,
) -> list[Chunk]:
    """한 장의 쪽들 → 조각. `pages`는 `chapter_pages`로 고른 그 장의 쪽만 준다.

    (쪽, 절) 하나가 조각 하나. 절 제목이 글자에 없는 판은 쪽 하나가 조각 하나다.
    글이 절 제목 한 줄뿐인 조각(제목 바로 뒤에 제목이 올 때, 쪽 끝에 제목만 남을 때)은
    만들지 않고 그 제목을 다음 조각 글 맨 앞에 붙인다 (위치·절은 다음 조각 것).
    장 안에서 인쇄 쪽 번호가 1씩 늘지 않으면 오류 (쪽을 빠뜨렸거나 장을 잘못 잘랐다는 뜻).
    """
    # 1단계: (쪽 번호, 절, 제목, 글, 제목뿐인가) 목록
    raw: list[tuple[int, tuple[int, ...] | None, str | None, str, bool]] = []
    section: tuple[int, ...] | None = None
    section_title: str | None = None
    prev_no: int | None = None
    for page in pages:
        f = _frame(page)
        if not any(ln.strip() for ln in f.body):
            logger.warning("%s: 글자가 없는 쪽을 건너뜀 (PDF %d쪽)", doc_id, page.page)
            continue
        if f.number is None:
            raise GuidelineIndexError(f"{doc_id}: 쪽 번호를 못 읽음 (PDF {page.page}쪽)")
        if prev_no is not None and f.number != prev_no + 1:
            raise GuidelineIndexError(
                f"{doc_id}: 쪽 번호가 1씩 늘지 않는다 ({prev_no} 다음 {f.number}, PDF {page.page})"
            )
        prev_no = f.number
        # 쪽 본문을 절 제목 줄에서 끊는다. 끊은 조각마다 (절, 제목, 줄들, 제목으로 시작했나)
        segments: list[list] = [[section, section_title, [], False]]
        for ln in f.body:
            if _is_chapter_header(ln.strip(), chapter):
                continue  # 옛 판은 장 첫 쪽 본문 맨 앞에 장 제목이 한 번 더 있다
            sec = _section_of(ln)
            if sec is not None and _follows(section, sec[0]):
                section, section_title = sec[0], sec[1]
                # 절 제목은 따로 한 문단으로 둔다 (아래 본문과 한 줄로 이어 붙지 않게)
                segments.append([section, section_title, [ln, ""], True])
                continue
            segments[-1][2].append(ln)
        for sec_nums, sec_title, seg_lines, starts_heading in segments:
            text = _paragraphs(seg_lines)
            if text:
                heading_only = starts_heading and text == seg_lines[0].strip()
                raw.append((f.number, sec_nums, sec_title, text, heading_only))

    # 2단계: 제목뿐인 조각은 다음 조각 앞에 붙인다
    merged: list[tuple[int, tuple[int, ...] | None, str | None, str]] = []
    pending: list[str] = []
    for no, sec_nums, sec_title, text, heading_only in raw:
        if heading_only:
            pending.append(text)
            continue
        merged.append((no, sec_nums, sec_title, "\n".join([*pending, text])))
        pending = []
    for text in pending:
        # 장의 맨 끝에 제목만 남은 드문 경우: 붙일 다음 조각이 없어 앞 조각 끝에 붙인다
        if not merged:
            raise GuidelineIndexError(f"{doc_id}: 장에 제목 말고 글이 없다")
        no, sec_nums, sec_title, prev_text = merged[-1]
        merged[-1] = (no, sec_nums, sec_title, prev_text + "\n" + text)

    # 3단계: 조각 만들기. chunk_id의 순번은 쪽마다 1부터
    chunks: list[Chunk] = []
    seq_by_page: dict[int, int] = {}
    for no, sec_nums, sec_title, text in merged:
        seq = seq_by_page[no] = seq_by_page.get(no, 0) + 1
        sec_str = ".".join(str(n) for n in sec_nums) if sec_nums else None
        attrs = {"chapter": chapter.title}
        if sec_str:
            attrs["section"] = sec_str
            attrs["section_title"] = sec_title or ""
        chunks.append(
            Chunk(
                chunk_id=f"{index_version}:{doc_id}:{no:04d}-{seq}",
                index_version=index_version,
                doc_id=doc_id,
                chunk_kind="guideline",
                location=Location(
                    kind="page",
                    start=no,
                    end=no,
                    label=_loc_label(no, chapter, sec_str, converted),
                ),
                edition=edition,
                text=text,
                source_kind="guideline",
                attrs=attrs,
            )
        )
    return chunks


def _as_date(v: object) -> date:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v))
    except ValueError as e:
        raise GuidelineIndexError(f"시행일을 읽을 수 없다: {v!r}") from e


def edition_doc_id(row: dict) -> str:
    return f"심사기준_{int(row['rule_no'])}_{_as_date(row['effective_from']).strftime('%Y%m%d')}"


def guideline_editions(table: list[dict]) -> dict[str, Edition]:
    """판 표 → {doc_id: 판본}. 끝 = 표의 `effective_to`, 없으면 다음 판 전날, 마지막 판은 현행.

    표에 없는 판(받지 못한 중간 판)이 있으면 `effective_to`로 앞 판의 끝을 줄여야 한다.
    그러면 빈 기간에는 조각이 없다 (검색은 0개, 판본 모름 처리는 F2 도구 몫).
    `effective_to`가 시행일보다 이르거나 다음 판 시행일 이상이면(겹침) 오류.
    """
    rows = sorted(table, key=lambda r: _as_date(r["effective_from"]))
    starts = [_as_date(r["effective_from"]) for r in rows]
    if len(set(starts)) != len(starts):
        raise GuidelineIndexError("판 표에 시행일이 같은 판이 둘 있다")
    out: dict[str, Edition] = {}
    for i, r in enumerate(rows):
        next_start = starts[i + 1] if i + 1 < len(rows) else None
        if r.get("effective_to") is not None:
            end = _as_date(r["effective_to"])
            if end < starts[i]:
                raise GuidelineIndexError(f"{edition_doc_id(r)}: effective_to가 시행일보다 이르다")
            if next_start is not None and end >= next_start:
                raise GuidelineIndexError(
                    f"{edition_doc_id(r)}: effective_to({end})가 다음 판({next_start})과 겹친다"
                )
        else:
            end = next_start - timedelta(days=1) if next_start else None
        out[edition_doc_id(r)] = Edition(
            status="confirmed",
            effective_from=starts[i],
            effective_to=end,
            label=r.get("label") or f"특허청 예규 제{int(r['rule_no'])}호",
        )
    return out


def extract_pages(pdf_path: Path) -> list[PageText]:
    """`pdftotext -layout`으로 쪽마다 줄 목록을 뽑는다 (쪽 구분은 form feed, poppler 필요)."""
    if not Path(pdf_path).is_file():
        raise GuidelineIndexError(f"PDF가 없다: {pdf_path}")
    try:
        r = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as e:
        raise GuidelineIndexError("pdftotext(poppler)가 없다: brew install poppler") from e
    if r.returncode != 0:
        raise GuidelineIndexError(f"pdftotext 실패({r.returncode}): {pdf_path}")
    texts = r.stdout.split("\f")
    if texts and not texts[-1].strip():
        texts.pop()  # 마지막 form feed 뒤의 빈 칸
    return [PageText(page=i, lines=t.splitlines()) for i, t in enumerate(texts, 1)]


def build_index(
    cfg: dict, extract=extract_pages, base_dir: Path | None = None
) -> tuple[list[Chunk], list[dict]]:
    """설정 → (조각 전부, 판마다 조각 수 기록). 한 판이라도 장을 못 찾으면 오류."""
    index_version = cfg["index_version"]
    if not is_index_version("law", index_version):
        raise GuidelineIndexError(f"법령 색인 판 이름이 아니다: {index_version}")
    chapters = [
        Chapter(int(c["part"]), int(c["chapter"]), str(c["title"])) for c in cfg["chapters"]
    ]
    table = cfg["editions"]
    if not table or not chapters:
        raise GuidelineIndexError("설정에 판 표나 장 목록이 비어 있다")
    editions = guideline_editions(table)
    raw_dir = Path(cfg["raw_dir"])
    if base_dir is not None and not raw_dir.is_absolute():
        raw_dir = base_dir / raw_dir
    all_chunks: list[Chunk] = []
    report: list[dict] = []
    for row in sorted(table, key=lambda r: _as_date(r["effective_from"])):
        doc_id = edition_doc_id(row)
        converted = bool(row.get("converted", False))
        pages = extract(raw_dir / row["file"])
        per_chapter: dict[str, int] = {}
        page_count = 0
        for ch in chapters:
            try:
                rng = chapter_pages(pages, ch)
            except GuidelineIndexError as e:
                raise GuidelineIndexError(f"{doc_id}: {e}") from e
            sub = [p for p in pages if p.page in rng]
            page_count += len(sub)
            chunks = chunk_guideline(sub, doc_id, editions[doc_id], index_version, ch, converted)
            if not chunks:
                raise GuidelineIndexError(f"{doc_id}: {ch.label} {ch.title} 조각이 0개다")
            per_chapter[f"{ch.label} {ch.title}"] = len(chunks)
            all_chunks.extend(chunks)
        report.append(
            {
                "doc_id": doc_id,
                "pages": page_count,
                "chunks": sum(per_chapter.values()),
                "per_chapter": per_chapter,
                "with_sections": any(
                    c.attrs and "section" in c.attrs for c in all_chunks if c.doc_id == doc_id
                ),
            }
        )
    seen: set[str] = set()
    for c in all_chunks:
        if c.chunk_id in seen:
            raise GuidelineIndexError(f"chunk_id가 겹친다: {c.chunk_id}")
        seen.add(c.chunk_id)
        why = check_law_chunk(
            c.chunk_kind, c.edition.status, c.source_kind, c.decided_on, c.speaker
        )
        if why:
            raise GuidelineIndexError(f"{c.chunk_id}: {why}")
    return all_chunks, report


def write_jsonl(chunks: list[Chunk], out: str | Path, force: bool = False) -> None:
    """chunk_id 순으로 한 줄에 조각 하나. 같은 입력이면 같은 바이트. force 없이는 안 덮는다."""
    p = Path(out)
    if p.exists() and not force:
        raise GuidelineIndexError(f"이미 있는 파일이라 덮어쓰지 않는다 (--force로 덮음): {p}")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    lines = [c.model_dump_json() for c in sorted(chunks, key=lambda c: c.chunk_id)]
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(p)


def main(argv: list[str] | None = None, extract=extract_pages) -> int:
    ap = argparse.ArgumentParser(description="심사기준 PDF → 색인 조각 JSONL")
    ap.add_argument("--config", required=True, help="config/index/guidelines.yaml")
    ap.add_argument("--force", action="store_true", help="이미 있는 출력 파일을 덮어쓴다")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    try:
        # 출력이 이미 있으면 PDF를 읽기 전에 멈춘다 (오래 걸리는 일을 헛돌리지 않음)
        if Path(cfg["out"]).exists() and not args.force:
            raise GuidelineIndexError(
                f"이미 있는 파일이라 덮어쓰지 않는다 (--force로 덮음): {cfg['out']}"
            )
        chunks, report = build_index(cfg, extract=extract)
        write_jsonl(chunks, cfg["out"], force=args.force)
    except (GuidelineIndexError, KeyError) as e:
        logger.error("심사기준 색인 실패: %s", e)
        return 1
    for r in report:
        parts = ", ".join(f"{k} {v}" for k, v in r["per_chapter"].items())
        note = "" if r["with_sections"] else " (절 제목이 그림이라 쪽 단위)"
        logger.info("%s: 쪽 %d, 조각 %d (%s)%s", r["doc_id"], r["pages"], r["chunks"], parts, note)
    logger.info("만듦: %s (조각 %d개, 판 %d개)", cfg["out"], len(chunks), len(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
